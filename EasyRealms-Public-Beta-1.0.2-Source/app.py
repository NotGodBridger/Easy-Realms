from __future__ import annotations
import json
import os
import ipaddress
from pathlib import Path
import sys
import threading
import time
from diagnostics import create_support_bundle, finish_diagnostics, log_exception, log_warning, start_diagnostics
from legal import APP_VERSION

DIAGNOSTICS = start_diagnostics(APP_VERSION) if __name__ == '__main__' else None

from PySide6.QtCore import Qt, QThread, Signal, QTimer, QPropertyAnimation, QEasingCurve, QProcess, QUrl, QSettings, QRectF, QSize, QPoint, QPointF, QVariantAnimation, QEvent, QParallelAnimationGroup, qInstallMessageHandler
from PySide6.QtGui import QColor, QPainter, QPixmap, QFontDatabase, QDesktopServices, QLinearGradient, QIcon, QFontMetricsF, QFont, QPainterPath
from PySide6.QtWidgets import (QApplication, QWidget, QLabel, QPushButton, QVBoxLayout, QHBoxLayout,
    QGridLayout, QLineEdit, QComboBox, QSpinBox, QCheckBox, QFileDialog,
    QProgressBar, QPlainTextEdit, QGraphicsOpacityEffect, QFrame, QScrollArea, QSizePolicy, QLayout, QStackedLayout, QStackedWidget, QStyleOptionButton, QStyle, QMessageBox, QTabWidget, QMenu, QDialog, QTextBrowser)
from addons import AddonManager, FABRIC_PRESETS
from automation import parse_player_count, recommend_resources, restart_decision, total_memory_gb
from backend import Catalog, create_server, java_major
from java_runtime import ensure_java
from legal import AGREEMENT_HTML, DISCLAIMER, agreement_is_current, record_acceptance
from performance import ProcessMonitor, format_memory, format_uptime, load_message
from player_access import PlayerAccessError, load_access_snapshot, player_commands, validate_player_name
from playit_manager import (
    PLAYIT_DASHBOARD_URL,
    PLAYIT_DOWNLOAD_URL,
    check_playit_status,
    find_playit_executable,
    tunnel_target,
)
from port_forwarding import PortForwarder, mapping_requests
from server_health import blocking_issues, check_server, format_report
from server_manager import BackupStore, ServerLibrary, read_properties, update_properties
from server_updates import check_update, check_upgrade, install_update, upgrade_versions
from ui_guidance import creation_guidance

ROOT = Path(__file__).resolve().parent
ASSETS = ROOT/'assets'


class AgreementDialog(QDialog):
    """Blocking first-run agreement with an explicit, reviewable choice."""
    def __init__(self, parent=None, review_only=False):
        super().__init__(parent)
        self.setWindowTitle('Easy Realms agreement')
        self.setModal(True);self.resize(720,620);self.setMinimumSize(600,480)
        layout=QVBoxLayout(self);layout.setContentsMargins(24,22,24,22);layout.setSpacing(14)
        title=QLabel('EASY REALMS AGREEMENT');title.setObjectName('pageTitle');layout.addWidget(title)
        disclaimer=QLabel(DISCLAIMER);disclaimer.setWordWrap(True);disclaimer.setStyleSheet('font-weight:bold;color:#f2c26f;');layout.addWidget(disclaimer)
        text=QTextBrowser();text.setOpenExternalLinks(True);text.setHtml(AGREEMENT_HTML);layout.addWidget(text,1)
        buttons=QHBoxLayout();buttons.addStretch()
        if review_only:
            close=TextureButton('Close');close.clicked.connect(self.accept);buttons.addWidget(close);layout.addLayout(buttons)
            return
        self.decline_button=TextureButton('Decline and exit');self.decline_button.clicked.connect(self.reject);buttons.addWidget(self.decline_button)
        self.agree_button=TextureButton('I AGREE');self.agree_button.setObjectName('primary');self.agree_button.clicked.connect(self.accept);buttons.addWidget(self.agree_button);layout.addLayout(buttons)

    def accepted_agreement(self):
        return self.exec()==QDialog.Accepted

class Worker(QThread):
    result = Signal(object)
    failed = Signal(str)
    progress = Signal(int, str)
    def __init__(self, fn):
        super().__init__(); self.fn = fn
    def run(self):
        try: self.result.emit(self.fn(self.progress.emit))
        except Exception as exc:
            log_exception('Background operation failed',exc)
            self.failed.emit(str(exc))

class TextureButton(QPushButton):
    def __init__(self, text, texture=None):
        super().__init__(text)
        self.setAccessibleName(text); self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(44)
        self.setIconSize(QSize(20,20))
        self._hover_amount=0.0;self._press_amount=0.0
        self._hover_anim=QVariantAnimation(self);self._hover_anim.setDuration(160);self._hover_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._hover_anim.valueChanged.connect(lambda value:(setattr(self,'_hover_amount',float(value)),self.update()))
        self._press_anim=QVariantAnimation(self);self._press_anim.setDuration(110);self._press_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._press_anim.valueChanged.connect(lambda value:(setattr(self,'_press_amount',float(value)),self.update()))
        if texture:
            icon = 'refresh' if texture=='refresh' else 'play'
            self.setIcon(QIcon(str(ASSETS/f'launcher_button_pack/icons/{icon}_icon.png')))

    def setText(self,text):
        super().setText(text);self.setAccessibleName(text)

    def changeEvent(self,event):
        if event.type()==QEvent.EnabledChange:
            self.setCursor(Qt.PointingHandCursor if self.isEnabled() else Qt.ArrowCursor)
            if not self.isEnabled():
                self._hover_amount=0.0;self._press_amount=0.0
        super().changeEvent(event)

    def _animate(self,animation,current,target):
        animation.stop();animation.setStartValue(current);animation.setEndValue(target);animation.start()
    def enterEvent(self,event):
        if self.isEnabled():self._animate(self._hover_anim,self._hover_amount,1.0)
        super().enterEvent(event)
    def leaveEvent(self,event):
        self._animate(self._hover_anim,self._hover_amount,0.0);self._animate(self._press_anim,self._press_amount,0.0);super().leaveEvent(event)
    def mousePressEvent(self,event):
        if self.isEnabled() and event.button()==Qt.LeftButton:self._animate(self._press_anim,self._press_amount,1.0)
        super().mousePressEvent(event)
    def mouseReleaseEvent(self,event):
        self._animate(self._press_anim,self._press_amount,0.0);super().mouseReleaseEvent(event)

    def sizeHint(self):
        hint=super().sizeHint()
        ink=QFontMetricsF(self.font()).tightBoundingRect(self.text())
        extra=self.iconSize().width()+10 if not self.icon().isNull() else 0
        horizontal_padding=22 if self.objectName()=='tab' else 40
        return QSize(max(hint.width(),int(ink.width())+extra+horizontal_padding),max(hint.height(),int(ink.height())+26))

    def _fitted_font(self,available_width):
        font=QFont(self.font());minimum=13.0 if self.objectName()=='primary' else 10.0
        size=font.pointSizeF()
        if size<=0:return font
        while size>minimum and QFontMetricsF(font).tightBoundingRect(self.text()).width()>available_width:
            size-=0.5;font.setPointSizeF(size)
        return font

    def paintEvent(self,event):
        # The bundled display fonts have unusual ascender/descender metrics.
        # Centre the actual glyph bounds instead of Qt's nominal text line box.
        option=QStyleOptionButton();self.initStyleOption(option)
        icon=QIcon(self.icon());option.text='';option.icon=QIcon()
        painter=QPainter(self);painter.setRenderHint(QPainter.Antialiasing,False)
        self.style().drawControl(QStyle.CE_PushButton,option,painter,self)
        painter.save()
        clip=QPainterPath();clip.addRect(QRectF(self.rect()).adjusted(1,1,-1,-1));painter.setClipPath(clip)
        if self.isEnabled():
            painter.fillRect(self.rect(),QColor(255,255,255,int(15*self._hover_amount)))
            painter.fillRect(self.rect(),QColor(0,0,0,int(38*self._press_amount)))
        painter.restore()
        painter.translate(0,1.5*self._press_amount)
        icon_width=self.iconSize().width() if not icon.isNull() else 0
        gap=10 if icon_width else 0
        horizontal_padding=20 if self.objectName()=='tab' else 36
        available=max(1,self.width()-icon_width-gap-horizontal_padding)
        font=self._fitted_font(available);painter.setFont(font)
        ink=QFontMetricsF(font).tightBoundingRect(self.text())
        total=ink.width()+icon_width+gap
        minimum_left=8 if self.objectName()=='tab' else 12
        left=14 if self.objectName() in ('navMenu','dropdownItem') else max(minimum_left,(self.width()-total)/2)
        center_y=self.rect().center().y()
        if icon_width:
            mode=QIcon.Normal if self.isEnabled() else QIcon.Disabled
            pix=icon.pixmap(self.iconSize(),mode)
            painter.drawPixmap(int(left),int(center_y-self.iconSize().height()/2),pix)
        if self.isEnabled():colour='#f0f0f0'
        elif self.objectName()=='primary':colour='#9aa496'
        elif self.objectName()=='tab':colour='#7d827a'
        else:colour='#898e86'
        painter.setPen(QColor(colour))
        painter.drawText(QPointF(left+icon_width+gap-ink.left(),center_y-ink.center().y()),self.text())

class AnimatedDropdown(QWidget):
    toggled=Signal(bool)
    def __init__(self,label,items,parent=None):
        super().__init__(parent);self._label=label;self._open=False;self._icons={text:icon for text,_,icon,_ in items}
        outer=QVBoxLayout(self);outer.setContentsMargins(0,0,0,0);outer.setSpacing(3)
        self.header=TextureButton('');self.header.setObjectName('navMenu');self.header.setMinimumHeight(50);self.header.clicked.connect(self.toggle);outer.addWidget(self.header)
        self.panel=QFrame();self.panel.setObjectName('dropdownPanel');self.panel.setMaximumHeight(0);self.panel.setVisible(False)
        panel_layout=QVBoxLayout(self.panel);panel_layout.setContentsMargins(5,5,5,5);panel_layout.setSpacing(2)
        for text,callback,icon,tooltip in items:
            button=TextureButton(text);button.setObjectName('dropdownItem');button.setMinimumHeight(42)
            if icon:button.setIcon(QIcon(str(icon)))
            if tooltip:button.setToolTip(tooltip)
            button.clicked.connect(lambda checked=False,fn=callback:self.choose(fn));panel_layout.addWidget(button)
        outer.addWidget(self.panel)
        self._expanded_height=len(items)*42+max(0,len(items)-1)*2+10
        self._height_animation=QPropertyAnimation(self.panel,b'maximumHeight',self);self._height_animation.setDuration(220);self._height_animation.setEasingCurve(QEasingCurve.OutCubic)
        self._opacity=QGraphicsOpacityEffect(self.panel);self._opacity.setOpacity(0);self.panel.setGraphicsEffect(self._opacity)
        self._opacity_animation=QPropertyAnimation(self._opacity,b'opacity',self);self._opacity_animation.setDuration(170);self._opacity_animation.setEasingCurve(QEasingCurve.OutCubic)
        self._height_animation.finished.connect(self.animation_finished);self.update_header()
    def update_header(self):
        self.header.setText(self._label+('  ▴' if self._open else '  ▾'))
        icon=self._icons.get(self._label);self.header.setIcon(QIcon(str(icon)) if icon else QIcon())
    def set_label(self,label):self._label=label;self.update_header()
    def toggle(self):self.set_open(not self._open)
    def set_open(self,open_state):
        open_state=bool(open_state)
        if open_state==self._open:return
        self._open=open_state;self.panel.setVisible(True);self.update_header()
        self._height_animation.stop();self._opacity_animation.stop()
        self._height_animation.setStartValue(self.panel.maximumHeight());self._height_animation.setEndValue(self._expanded_height if open_state else 0)
        self._opacity_animation.setStartValue(self._opacity.opacity());self._opacity_animation.setEndValue(1.0 if open_state else 0.0)
        self._height_animation.start();self._opacity_animation.start();self.toggled.emit(open_state)
    def choose(self,callback):
        self.set_open(False);callback()
    def animation_finished(self):
        if not self._open:self.panel.setVisible(False)

class CommandInput(QLineEdit):
    def __init__(self):
        super().__init__();self.history=[];self.position=0;self.draft=''
        self.setPlaceholderText('Enter a command, e.g. help, list or say Hello')
        self.setAccessibleName('Server command')
    def remember(self,command):
        if not self.history or self.history[-1]!=command:self.history.append(command)
        self.history=self.history[-100:];self.position=len(self.history);self.draft='';self.clear()
    def keyPressEvent(self,event):
        if event.key()==Qt.Key_Up and self.history:
            if self.position==len(self.history):self.draft=self.text()
            self.position=max(0,self.position-1);self.setText(self.history[self.position]);return
        if event.key()==Qt.Key_Down and self.history:
            self.position=min(len(self.history),self.position+1)
            self.setText(self.draft if self.position==len(self.history) else self.history[self.position]);return
        super().keyPressEvent(event)

class Logo(QWidget):
    def __init__(self,width,height):
        super().__init__();self.setFixedSize(width,height)
        self.setAccessibleName('Easy Realms logo')
        self.pixmap=QPixmap(str(ASSETS/'logo.png'))
    def paintEvent(self,event):
        p=QPainter(self);p.setRenderHint(QPainter.SmoothPixmapTransform)
        source=QRectF(0,565,2048,917)
        scale=min(self.width()/source.width(),self.height()/source.height())
        target=QRectF(0,(self.height()-source.height()*scale)/2,source.width()*scale,source.height()*scale)
        p.drawPixmap(target,self.pixmap,source)

class Hero(QWidget):
    def __init__(self):
        super().__init__(); self.setMinimumHeight(280)
        self.art = QPixmap(str(ASSETS/'launcher-reference.png'))
        layout=QVBoxLayout(self); layout.setContentsMargins(36,32,36,32)
        heading=Logo(380,170); layout.addWidget(heading)
        sub=QLabel('A world of your own.');sub.setObjectName('heroSubtitle');layout.addWidget(sub)
        layout.addStretch()
        label=QLabel('BUILD IT. HOST IT. MAKE IT YOURS.');label.setObjectName('heroCaption');layout.addWidget(label)
    def paintEvent(self,event):
        p=QPainter(self);p.setRenderHint(QPainter.SmoothPixmapTransform)
        # Render only artwork from the user's launcher reference, excluding all
        # screenshot UI and account information. Aspect-fill, never stretch.
        source=QRectF(435,425,1494,505)
        ratio=self.width()/self.height()
        if source.width()/source.height()>ratio:
            width=source.height()*ratio;source.setX(source.x()+(source.width()-width)/2);source.setWidth(width)
        else:
            height=source.width()/ratio;source.setY(source.y()+(source.height()-height)/2);source.setHeight(height)
        p.drawPixmap(QRectF(self.rect()),self.art,source)
        shade=QLinearGradient(0,0,0,self.height());shade.setColorAt(0,QColor(0,0,0,155));shade.setColorAt(.55,QColor(0,0,0,0));shade.setColorAt(1,QColor(0,0,0,160));p.fillRect(self.rect(),shade)

class Window(QWidget):
    def __init__(self, offline=False):
        super().__init__()
        self.setWindowTitle('Easy Realms');self.resize(1220,820);self.setMinimumSize(920,620)
        data=Path(os.environ.get('EASY_REALMS_DATA',ROOT/'data'));data.mkdir(parents=True,exist_ok=True)
        self.data=data;self.library=ServerLibrary(data);self.backups=BackupStore(data);self.selected_entry=None
        self.settings=QSettings(str(data/'settings.ini'),QSettings.IniFormat)
        previous=QSettings('EasyServers','EasyServers')
        for key in previous.allKeys():
            if not self.settings.contains(key):self.settings.setValue(key,previous.value(key))
        self.kind='Vanilla';self.spec=None;self.server=None;self.jobs=[];self.generation=0;self.restart_pending=False;self.catalog_loading=False
        self.active_port_mappings=[];self.mapping_server=None;self.direct_forwarding_approvals=set();self.last_health_checks=[];self.doctor_report='';self.addon_context_key=None;self.pending_server_update=None;self.pending_server_upgrade=None
        self.server_started=False;self.stop_requested=False;self.running_server=None;self.runtime_config={}
        self.empty_since=None;self.last_player_count=None;self.server_started_at=None;self.crash_times=[];self.auto_backup_in_progress=False;self.recovery_pending=False;self.console_tail=''
        self.cancel=threading.Event();self.creating=False;self.offline=offline;self.animations=[]
        self.process_monitor=ProcessMonitor()
        self.process=QProcess(self);self.process.setProcessChannelMode(QProcess.MergedChannels)
        self.process.started.connect(self.performance_started);self.process.readyReadStandardOutput.connect(self.read_console);self.process.finished.connect(self.stopped);self.process.errorOccurred.connect(self.process_error);self.process.stateChanged.connect(self.command_state)
        self.playit_process=QProcess(self);self.playit_process.setStandardOutputFile(QProcess.nullDevice());self.playit_process.setStandardErrorFile(QProcess.nullDevice());self.playit_process.finished.connect(self.playit_setup_finished);self.playit_process.errorOccurred.connect(self.playit_setup_error);self.playit_cancel_message=''
        self.playit_setup_timer=QTimer(self);self.playit_setup_timer.setSingleShot(True);self.playit_setup_timer.setInterval(10*60*1000);self.playit_setup_timer.timeout.connect(self.playit_setup_timeout)
        self.performance_timer=QTimer(self);self.performance_timer.setInterval(2000);self.performance_timer.timeout.connect(self.update_performance);self.performance_timer.start()
        self.automation_timer=QTimer(self);self.automation_timer.setInterval(30000);self.automation_timer.timeout.connect(self.poll_automation);self.automation_timer.start()
        self.forwarding_timer=QTimer(self);self.forwarding_timer.setInterval(5*60*1000);self.forwarding_timer.timeout.connect(self.renew_port_mappings)
        outer=QHBoxLayout(self);outer.setContentsMargins(0,0,0,0);outer.setSpacing(0)
        sidebar=QFrame();sidebar.setObjectName('sidebar');sidebar.setMinimumWidth(196)
        nav_scroll=QScrollArea();nav_scroll.setFixedWidth(216);nav_scroll.setWidgetResizable(True);nav_scroll.setFrameShape(QFrame.NoFrame);nav_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff);nav_scroll.setWidget(sidebar);outer.addWidget(nav_scroll)
        nav=QVBoxLayout(sidebar);nav.setContentsMargins(16,28,16,20);nav.setSpacing(10)
        brand=Logo(184,83);nav.addWidget(brand)
        nav.addWidget(QLabel('Your PC. Your community.'));nav.addSpacing(20)
        caption=QLabel('SERVER SOFTWARE');caption.setObjectName('navCaption');nav.addWidget(caption)
        software_items=[]
        for kind,desc,icon in [('Vanilla','Classic Minecraft','java'),('Fabric','Modded adventures','settings'),('Paper','Plugins & performance','installations'),('Bedrock','Windows, mobile & consoles','bedrock')]:
            software_items.append((kind,lambda k=kind:self.select_kind(k),ASSETS/f'launcher_button_pack/icons/{icon}_icon.png',desc))
        self.software_selector=AnimatedDropdown('Vanilla',software_items);nav.addWidget(self.software_selector)
        nav.addStretch()
        library_caption=QLabel('LIBRARY');library_caption.setObjectName('navCaption');nav.addWidget(library_caption)
        library_items=[
            ('My servers',lambda:self.show_page(6),ASSETS/'launcher_button_pack/icons/java_icon.png','Open your server library'),
            ('Import server',self.open_existing,ASSETS/'launcher_button_pack/icons/installations_icon.png','Add an existing server folder'),
            ('Change log',lambda:self.show_page(3),ASSETS/'launcher_button_pack/icons/refresh_icon.png','See what changed'),
            ('About & legal',lambda:self.show_page(10),ASSETS/'launcher_button_pack/icons/settings_icon.png','Agreement, privacy and diagnostic logs')]
        self.library_selector=AnimatedDropdown('Library',library_items);nav.addWidget(self.library_selector)
        self.software_selector.toggled.connect(lambda opened:self.library_selector.set_open(False) if opened else None)
        self.library_selector.toggled.connect(lambda opened:self.software_selector.set_open(False) if opened else None)
        nav.addWidget(QLabel(APP_VERSION.upper()))
        main=QVBoxLayout();main.setSpacing(0);outer.addLayout(main,1)
        top=QFrame();top.setObjectName('top');tl=QVBoxLayout(top);tl.setContentsMargins(28,20,28,0);tl.setSpacing(8)
        title_row=QHBoxLayout();title_row.setSpacing(14)
        self.section_title=QLabel('MINECRAFT: VANILLA SERVER');self.section_title.setObjectName('section');title_row.addWidget(self.section_title);title_row.addStretch()
        self.selection_banner=QFrame();self.selection_banner.setObjectName('selectionChip');selection_row=QHBoxLayout(self.selection_banner);selection_row.setContentsMargins(10,3,4,3);selection_row.setSpacing(8)
        self.selection_status=QLabel('NO SERVER SELECTED');self.selection_status.setObjectName('selectionStatus');selection_row.addWidget(self.selection_status)
        self.selection_action=TextureButton('CHOOSE');self.selection_action.setFixedHeight(34);self.selection_action.setMinimumWidth(86);self.selection_action.clicked.connect(lambda:self.show_page(6));selection_row.addWidget(self.selection_action);title_row.addWidget(self.selection_banner)
        tl.addLayout(title_row)
        tabs=QHBoxLayout();tabs.setSpacing(8);self.tabs=[]
        self.tab_pages=(6,0,7,2,9,8,5)
        for i,text in enumerate(['My servers','Create','Manage','Console','Players','Add-ons','Share']):
            b=TextureButton(text);b.setObjectName('tab');b.setCheckable(True);b.clicked.connect(lambda checked=False,n=self.tab_pages[i]:self.navigate(n));tabs.addWidget(b);self.tabs.append(b)
        self.tabs_by_page=dict(zip(self.tab_pages,self.tabs))
        tabs.addStretch()
        tab_content=QWidget();tab_content.setLayout(tabs);tabs.setContentsMargins(0,0,0,0)
        tab_scroll=QScrollArea();tab_scroll.setWidgetResizable(True);tab_scroll.setFrameShape(QFrame.NoFrame);tab_scroll.setWidget(tab_content);tab_scroll.setFixedHeight(58);tab_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff);tab_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        tl.addWidget(tab_scroll)
        main.addWidget(top)
        self.pages=QStackedWidget();self.pages.layout().setStackingMode(QStackedLayout.StackAll);main.addWidget(self.pages,1)
        home_scroll=QScrollArea();home_scroll.setWidgetResizable(True);home_scroll.setFrameShape(QFrame.NoFrame);home_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        home=QWidget();hl=QVBoxLayout(home);hl.setContentsMargins(0,0,0,0);hl.setSpacing(0);hl.setSizeConstraint(QLayout.SetMinimumSize)
        self.hero=Hero();hl.addWidget(self.hero,1)
        dock=QFrame();dock.setObjectName('dock');dl=QHBoxLayout(dock);dl.setContentsMargins(24,18,24,18);dl.setSpacing(20)
        selector=QVBoxLayout();selector.addWidget(QLabel('MINECRAFT VERSION'))
        vr=QHBoxLayout();self.version=QComboBox();self.version.setMinimumWidth(140);self.version.setFixedHeight(44);self.version.setPlaceholderText('Loading versions…');self.version.currentTextChanged.connect(self.resolve);vr.addWidget(self.version,1)
        self.refresh=TextureButton('Refresh','refresh');self.refresh.setFixedHeight(44);self.refresh.setToolTip('Reload supported versions for the selected server software');self.refresh.clicked.connect(self.load_versions);vr.addWidget(self.refresh);selector.addLayout(vr);dl.addLayout(selector,1)
        self.setup=TextureButton('CONTINUE TO SETUP');self.setup.setObjectName('primary');self.setup.setMinimumSize(236,64);self.setup.setMaximumWidth(280);self.setup.clicked.connect(lambda:self.show_page(1));dl.addWidget(self.setup)
        hl.addWidget(dock)
        info=QFrame();info.setObjectName('info');il=QHBoxLayout(info);il.setContentsMargins(26,10,24,10);il.setSpacing(16)
        self.detail=QLabel('Loading official versions…');self.detail.setWordWrap(True);il.addWidget(self.detail,1)
        import_home=TextureButton('IMPORT SERVER');import_home.setToolTip('Add a Minecraft server folder you already use');import_home.clicked.connect(self.open_existing);il.addWidget(import_home);hl.addWidget(info)
        home_scroll.setWidget(home);self.pages.addWidget(home_scroll)
        scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setFrameShape(QFrame.NoFrame)
        config=QWidget();cl=QVBoxLayout(config);cl.setContentsMargins(28,24,28,24);cl.setSpacing(18);cl.setSizeConstraint(QLayout.SetMinimumSize);scroll.setWidget(config);self.pages.addWidget(scroll)
        heading=QLabel('MAKE IT YOURS');heading.setObjectName('pageTitle');cl.addWidget(heading)
        self.config_detail=QLabel('Choose a Minecraft version on the Create tab.');self.config_detail.setWordWrap(True);cl.addWidget(self.config_detail)
        self.panel=QFrame();grid=QGridLayout(self.panel);grid.setContentsMargins(0,0,0,0);grid.setHorizontalSpacing(18);grid.setVerticalSpacing(14);grid.setColumnStretch(1,1)
        self.panel.setSizePolicy(QSizePolicy.Expanding,QSizePolicy.Fixed);cl.addWidget(self.panel)
        self.name=QLineEdit('My Minecraft Server');self.name.setPlaceholderText('Letters, numbers, spaces, - or _');self.ram=QSpinBox();self.ram.setRange(1,128);self.ram.setValue(4);self.ram.setSuffix(' GB')
        self.folder=QLineEdit(str(data/'servers'));self.folder.setPlaceholderText('Where the new server folder will be created');self.java=QLineEdit(self.settings.value('java','Automatic'))
        self.contact=QLineEdit(self.settings.value('contact',''));self.contact.setPlaceholderText('Public project URL or contact email');self.contact.editingFinished.connect(self.contact_changed)
        self.form_rows=[];self.form_labels=[]
        for row,(label,control,fn) in enumerate([('Server name',self.name,None),('Memory',self.ram,None),('Save location',self.folder,self.choose_folder),('Java (Automatic recommended)',self.java,self.choose_java),('Paper API contact',self.contact,None)]):
            label_widget=QLabel(label);grid.addWidget(label_widget,row,0);self.form_labels.append(label_widget)
            wrap=QWidget();layout=QHBoxLayout(wrap);layout.setContentsMargins(0,0,0,0);layout.setSpacing(10);control.setFixedHeight(44);layout.addWidget(control,1)
            if fn:
                b=TextureButton('Browse');b.setFixedSize(90,44);b.clicked.connect(fn);layout.addWidget(b)
            wrap.setFixedHeight(44);grid.addWidget(wrap,row,1);grid.setRowMinimumHeight(row,44);self.form_rows.append(wrap)
        self.setup_tip=QLabel('Java set to Automatic downloads the required runtime into data/java when needed. Paper requires a contact URL or email for its download API.');self.setup_tip.setWordWrap(True);self.setup_tip.setObjectName('muted');cl.addWidget(self.setup_tip)
        self.eula=QCheckBox('I have read and accept the Minecraft EULA');self.eula.toggled.connect(self.update_create);cl.addWidget(self.eula)
        link=QLabel('<a href="https://www.minecraft.net/eula" style="color:#9bdd84">Read the Minecraft EULA ↗</a>');link.setOpenExternalLinks(True);cl.addWidget(link)
        self.create_state=QLabel('Choose a compatible version first.');self.create_state.setObjectName('createState');self.create_state.setWordWrap(True);self.create_state.setProperty('state','waiting');cl.addWidget(self.create_state)
        actions=QHBoxLayout();self.create=TextureButton('CREATE SERVER');self.create.setObjectName('primary');self.create.setMinimumHeight(56);self.create.clicked.connect(self.build);actions.addWidget(self.create,1)
        self.abort=TextureButton('Cancel download');self.abort.clicked.connect(lambda:self.cancel.set());self.abort.setEnabled(False);actions.addWidget(self.abort);cl.addLayout(actions);cl.addStretch()
        self.name.textChanged.connect(self.update_create);self.folder.textChanged.connect(self.update_create)
        console_page=QWidget();cp=QVBoxLayout(console_page);cp.setContentsMargins(28,24,28,24);cp.setSpacing(18)
        title=QLabel('SERVER CONSOLE');title.setObjectName('pageTitle');cp.addWidget(title)
        self.server_label=QLabel('Create or open a server to begin.');self.server_label.setWordWrap(True);cp.addWidget(self.server_label)
        self.performance_panel=QFrame();self.performance_panel.setObjectName('performancePanel')
        performance_layout=QHBoxLayout(self.performance_panel);performance_layout.setContentsMargins(16,10,16,10);performance_layout.setSpacing(20)
        self.performance_values={}
        for caption,key in [('CPU','cpu'),('MEMORY','memory'),('UPTIME','uptime'),('PLAYERS','players')]:
            metric=QVBoxLayout();metric.setSpacing(2)
            value=QLabel('—');value.setObjectName('metricValue');value.setAlignment(Qt.AlignCenter)
            name=QLabel(caption);name.setObjectName('metricCaption');name.setAlignment(Qt.AlignCenter)
            metric.addWidget(value);metric.addWidget(name);performance_layout.addLayout(metric,1);self.performance_values[key]=value
        self.performance_note=QLabel('Start the server to see live performance.');self.performance_note.setObjectName('muted');self.performance_note.setWordWrap(True);performance_layout.addWidget(self.performance_note,2)
        cp.addWidget(self.performance_panel)
        self.console=QPlainTextEdit();self.console.setReadOnly(True);self.console.setMaximumBlockCount(2000);self.console.setPlaceholderText('Server output will appear here after launch.');cp.addWidget(self.console,1)
        command_row=QHBoxLayout();command_row.setSpacing(12)
        self.command_input=CommandInput();self.command_input.setFixedHeight(46);self.command_input.returnPressed.connect(self.send_command);self.command_input.setEnabled(False)
        self.send=TextureButton('Send');self.send.setFixedHeight(46);self.send.setEnabled(False);self.send.clicked.connect(self.send_command)
        command_row.addWidget(self.command_input,1);command_row.addWidget(self.send);cp.addLayout(command_row)
        hint=QLabel('Enter to send • Up / Down for command history • Commands can include a leading /');hint.setObjectName('muted');hint.setWordWrap(True);cp.addWidget(hint)
        controls=QHBoxLayout();self.launch=TextureButton('LAUNCH SERVER','launch_launch');self.launch.setObjectName('primary');self.launch.setMinimumHeight(56);self.launch.clicked.connect(self.start);self.launch.setEnabled(False)
        self.restart=TextureButton('Restart server');self.restart.setToolTip('Save the world, stop cleanly, then launch this server again');self.restart.clicked.connect(self.restart_server);self.restart.setEnabled(False)
        self.stop=TextureButton('Stop server');self.stop.clicked.connect(self.stop_server);self.stop.setEnabled(False);controls.addWidget(self.launch);controls.addWidget(self.restart);controls.addWidget(self.stop);controls.addStretch();cp.addLayout(controls);self.pages.addWidget(console_page)
        changelog=QScrollArea();changelog.setWidgetResizable(True);changelog.setFrameShape(QFrame.NoFrame)
        changelog_content=QWidget();log_layout=QVBoxLayout(changelog_content);log_layout.setContentsMargins(28,24,28,24);log_layout.setSpacing(18)
        log_title=QLabel('CHANGE LOG');log_title.setObjectName('pageTitle');log_layout.addWidget(log_title)
        for version,items in [
            ('Public Beta 1.0.2 • Friendlier interface',['I restored square, bevelled Minecraft Launcher-style buttons with smoother hover and press feedback.','I simplified the Create page by removing the boxed setup guide and long instruction block, replacing them with one useful status line and a direct Import server action.','I moved the selected-server state into a compact control beside the page title so it stays visible without taking over the screen.','I made first launch verify every required component, automatically install missing or incompatible source dependencies, and re-check them before opening Easy Realms.','I added Mojangles (Minecraft Seven v2) for ordinary interface text while keeping Minecraft Ten for headings and major actions.','I renamed the first creation action to Continue to setup so it no longer implies the server will be created immediately.','I added live server status badges and a highlighted selected server in My servers.','I added direct Create and Import actions to the empty library screen and clearer navigation tooltips.']),
            ('Public Beta 1.0 • First public beta',['I added a one-click privacy-scrubbed bug report ZIP that excludes worlds, settings, console output and account data.','I moved server software and library actions into two smooth Minecraft Launcher-style sidebar dropdown menus.','I added an eased fade and slide when switching between the main tabs.','I replaced Futura with the Minecraft font throughout the interface.','I fixed Linux automatic Java setup to safely preserve the internal links used by official Temurin archives.','I tested extraction and Java startup against the current official Temurin 21 Linux x64 JRE.','I added a private per-launch diagnostic log with Python, thread, Qt, server-process and clean-shutdown reporting in data/logs.','I removed the unreliable native launcher and made START HERE use the official bundled runtime directly.','I added the complete LGPLv3 text and clarified the bundled Qt for Python notice.','I removed obsolete packaging code and completed the portable release audit.']),
            ('0.12.0 • Public release preparation',['I added a first-run Easy Realms agreement with a permanent review page and versioned local acceptance record.','I added a prominent notice that Easy Realms is not an official Minecraft product and is not approved by or associated with Mojang or Microsoft.','I fixed Linux download requests that could be rejected with HTTP 403 and added verified automatic Java runtime setup for Linux x64.','I added release notes, privacy information, third-party notices and package checksums.']),
            ('0.11.0 • Controlled version upgrades',['I added forward-only Minecraft version upgrades with a compatibility preflight.','I made Easy Realms validate or install the target Java runtime before server files change.','I added Modrinth compatibility checks and automatic compatible-version migration for managed Fabric mods and Paper plugins.','I blocked downgrades, Stable/Preview switching and unmanaged add-ons, and made failed upgrades automatically restore their mandatory backup.']),
            ('0.10.0 • Safe server updates',['I added same-version update checks for Vanilla, Fabric, Paper and Bedrock server software.','I made every update create a complete recovery backup before verified server files are replaced.','I kept Minecraft version upgrades separate so a routine Paper build or Fabric loader update cannot silently upgrade a world.','I preserved worlds, settings, add-ons and player access files during supported updates.']),
            ('0.9.3 • Portable launch restored',['I withdrew the incompatible one-file launcher and restored the portable Windows launcher that previously opened successfully.','I added a clear extraction checker and a fallback copy of the required Python DLL so incomplete folders fail with useful instructions instead of a Windows system error.']),
            ('0.9.0 • Player access',['I added a dedicated Players page for Java and Bedrock servers.','I added safe allow-list add, remove, enable and list controls with edition-aware commands and strict player-name validation.','I added operator grant and revoke controls with an explicit trust warning and confirmation before granting elevated access.','I added read-only summaries of the server’s local allow-list and Java operator files so access can be reviewed even while the server is stopped.']),
            ('0.8.2 • Sharing safety audit',['I added clear, separate instructions for hosts and friends joining Java or Bedrock servers.','I made Easy Realms run only the machine-installed Playit command from Windows Program Files and leave standalone or user-writable copies untouched.','I stopped Easy Realms from handling Playit claim links, shortened direct router leases to ten minutes and made direct sharing require verified accounts plus an allow-list every launch.','I tightened UPnP discovery and cleanup so router responses stay on the responding private gateway and Easy Realms does not remove a mapping it no longer owns.']),
            ('0.8.1 • Safer sharing',['I added an in-app Playit connection flow that opens Playit’s own one-time account approval page without storing passwords or agent secrets.','I added selected-server tunnel values, Playit status checks and direct links to the official download and tunnel dashboard.','I made direct UPnP require session approval, verified accounts and temporary renewable leases; routers demanding permanent rules are refused.']),
            ('0.8.0 • Live performance',['I added live CPU, memory, uptime and player-count monitoring to the server console.','I added simple load guidance so high CPU or memory pressure is understandable without technical tools.']),
            ('0.7.3 • Asset cleanup',['I removed unused launcher textures, preview images, metadata and spare icons from the source and portable builds.','I kept only the fonts, branding, hero artwork and six interface icons that Easy Realms actually loads.']),
            ('0.7.2 • Interface fixes',['I corrected button text and icon centring, including long labels that now shrink cleanly instead of being cut off.','I disabled Create server until a compatible version is actually ready and added clear loading and unavailable states.','I improved disabled, hover, press and focus feedback and stopped the bottom status message from being clipped.','I repaired Bedrock version loading after Minecraft moved its downloads to the official links service.']),
            ('0.7.0 • Automation and protection',['I added Easy Mode recommendations based on the host PC’s memory and server type.','I added optional pre-launch backups with automatic retention and graceful empty-server shutdown.','I added controlled crash recovery with a three-attempt safety limit.']),
            ('0.6.1 • Cleaner navigation',['I reduced the main navigation to the six things used most often.','I grouped server settings, Server Doctor and backups into focused sections.','I moved rare server actions into a More menu and separated add-on browsing from installed add-ons.']),
            ('0.6.0 • Mods and plugins',['I added in-app Modrinth search filtered to the selected Minecraft version and Fabric or Paper loader.','I added verified installs, updates and removal with automatic required-dependency handling.','I added player-side requirement warnings plus Fabric performance and Simple Voice Chat presets.']),
            ('0.5.0 • Server Doctor',['I added one-click server readiness checks with a copyable tester report.','I added automatic pre-launch checks for missing files, Java, unsafe paths, ports, memory and storage.','I added clearer public-server security recommendations and unexpected-stop reporting.']),
            ('0.4.1 • Safer sharing guidance',['I made playit.gg the recommended way to share a server without giving friends your home IP address.','I added a direct shortcut from server settings to the exact playit setup guide.','I relabelled automatic router forwarding as an advanced alternative.']),
            ('0.4.0 • Automatic port forwarding',['I added opt-in UPnP router discovery for each server.','I open only the configured Minecraft port while the server runs, then remove Easy Realms’ mappings when it stops.','I added Java TCP and Bedrock TCP/UDP support, including custom server ports.']),
            ('0.3.0 • Bedrock Edition',['I added official Bedrock Dedicated Server downloads for Windows.','I added Bedrock creation, importing, settings, console commands, graceful restart and backups.','I added stable and Preview channels when Minecraft offers them.']),
            ('0.2.1 • Graceful restart',['I added a Restart server button that saves the world, waits for shutdown, then launches it again.']),
            ('0.2.0 • Server management',['I added My servers, including safe imports that leave existing worlds in place.','I added friendly settings for common server options.','I added recoverable backups and restores.','I added smooth hover and click feedback to buttons.']),
            ('0.1.8 • Portable launcher',['I added a Windows EXE with a custom app icon.','I moved settings, runtime downloads and default server folders into data.','I added verified automatic Java downloads when Automatic is selected.']),
            ('0.1.7 • Play with friends',['I added a playit.gg setup guide with tunnel settings, copy buttons and troubleshooting.']),
            ('0.1.6 • Console commands',['I added a command box with Enter and Send support.','I added Up/Down command history and support for commands with or without a leading slash.','I disabled command input when the server is stopped.']),
            ('0.1.5 • Easy Realms',['I renamed Easy Servers to Easy Realms.','I added a Bedrock Edition tab with a Coming Soon page.']),
            ('0.1.4 • Text alignment',['I centred button text using the visible letter shapes.','I added extra room around labels to prevent clipped text.']),
            ('0.1.3 • Interface polish',['I added the Easy Realms logo to the launcher and loading screen.','I styled regular interface text with the bundled interface font.','I aligned server icons and labels, refined button spacing and focus states.','I added this Change Log page.']),
            ('0.1.2 • A cleaner startup',['I added an animated loading window and setup-stage messages.','I moved installation output into a startup log.','I added startup retry and log access.']),
            ('0.1.1 • Launcher redesign',['I added the artwork panel, sidebar and separate settings and console tabs.','I fixed overlapping settings rows and added scrolling for smaller windows.']),
            ('0.1.0 • First build',['I added Vanilla, Fabric and Paper with live release catalogs.','I added server creation, Java checks, RAM settings and launch/stop controls.'])]:
            label=QLabel(version);label.setObjectName('subheading');label.setStyleSheet('color:#9bdd84;');log_layout.addWidget(label)
            for item in items:
                line=QLabel('• '+item);line.setWordWrap(True);log_layout.addWidget(line)
        log_layout.addStretch();changelog.setWidget(changelog_content);self.pages.addWidget(changelog)
        bedrock=QWidget();bedrock_layout=QVBoxLayout(bedrock);bedrock_layout.setContentsMargins(42,36,42,36);bedrock_layout.setSpacing(18)
        bedrock_layout.addStretch()
        edition=QLabel('BEDROCK EDITION');edition.setObjectName('pageTitle');edition.setAlignment(Qt.AlignCenter);bedrock_layout.addWidget(edition)
        ready=QLabel('READY TO HOST');ready.setAlignment(Qt.AlignCenter);ready.setStyleSheet('font-family:"Minecraft Ten";font-size:40px;color:#9bdd84;');bedrock_layout.addWidget(ready)
        message=QLabel('Create an official Windows Bedrock Dedicated Server for PC, mobile and supported console players. Bedrock runs natively and does not need Java.');message.setAlignment(Qt.AlignCenter);message.setWordWrap(True);bedrock_layout.addWidget(message)
        warning=QLabel('Easy Realms uses the current builds offered by Minecraft. Preview servers are experimental and should use a separate world.');warning.setObjectName('muted');warning.setAlignment(Qt.AlignCenter);warning.setWordWrap(True);bedrock_layout.addWidget(warning)
        bedrock_action=QHBoxLayout();bedrock_action.addStretch();bedrock_create=TextureButton('CREATE BEDROCK SERVER');bedrock_create.setObjectName('primary');bedrock_create.setMinimumSize(320,62);bedrock_create.clicked.connect(lambda:(self.select_kind('Bedrock'),self.show_page(0)));bedrock_action.addWidget(bedrock_create);bedrock_action.addStretch();bedrock_layout.addLayout(bedrock_action)
        bedrock_layout.addStretch();self.pages.addWidget(bedrock)
        from playit_guide import make_guide
        self.playit_page=make_guide(TextureButton);self.playit_page.setup_requested.connect(self.start_playit_setup);self.playit_page.setup_cancelled.connect(self.cancel_playit_setup);self.playit_page.status_requested.connect(self.refresh_playit_status);self.pages.addWidget(self.playit_page)
        library_page=QWidget();library_layout=QVBoxLayout(library_page);library_layout.setContentsMargins(28,24,28,24);library_layout.setSpacing(16)
        library_header=QHBoxLayout();library_heading=QLabel('MY SERVERS');library_heading.setObjectName('pageTitle');library_header.addWidget(library_heading);library_header.addStretch()
        add_server=TextureButton('Create a new server');add_server.clicked.connect(lambda:self.show_page(0));library_header.addWidget(add_server)
        import_server=TextureButton('Import a server');import_server.clicked.connect(self.open_existing);library_header.addWidget(import_server);library_layout.addLayout(library_header)
        intro=QLabel('All your worlds in one place. Importing a server keeps it in its current folder and never touches the world itself.');intro.setObjectName('muted');intro.setWordWrap(True);library_layout.addWidget(intro)
        self.library_scroll=QScrollArea();self.library_scroll.setWidgetResizable(True);self.library_scroll.setFrameShape(QFrame.NoFrame)
        self.library_content=QWidget();self.library_rows=QVBoxLayout(self.library_content);self.library_rows.setContentsMargins(0,8,8,8);self.library_rows.setSpacing(12);self.library_rows.addStretch()
        self.library_scroll.setWidget(self.library_content);library_layout.addWidget(self.library_scroll,1);self.pages.addWidget(library_page)
        manage=QWidget();manage_layout=QVBoxLayout(manage);manage_layout.setContentsMargins(28,20,28,20);manage_layout.setSpacing(12)
        self.manage_title=QLabel('SERVER SETTINGS');self.manage_title.setObjectName('pageTitle');manage_layout.addWidget(self.manage_title)
        self.manage_note=QLabel('Choose a server from My servers. Changes apply the next time the server starts.');self.manage_note.setObjectName('muted');self.manage_note.setWordWrap(True);manage_layout.addWidget(self.manage_note)
        self.manage_sections=QTabWidget();self.manage_sections.setObjectName('sections');manage_layout.addWidget(self.manage_sections,1)
        settings_scroll=QScrollArea();settings_scroll.setWidgetResizable(True);settings_scroll.setFrameShape(QFrame.NoFrame)
        settings_content=QWidget();settings_layout=QVBoxLayout(settings_content);settings_layout.setContentsMargins(16,16,16,16);settings_layout.setSpacing(14);settings_scroll.setWidget(settings_content);self.manage_sections.addTab(settings_scroll,'Settings')
        property_frame=QFrame();property_grid=QGridLayout(property_frame);property_grid.setHorizontalSpacing(18);property_grid.setVerticalSpacing(12);property_grid.setColumnStretch(1,1);settings_layout.addWidget(property_frame)
        self.manage_ram=QSpinBox();self.manage_ram.setRange(1,128);self.manage_ram.setSuffix(' GB')
        self.manage_java=QLineEdit();self.manage_java.setPlaceholderText('java, or the full path to java.exe')
        self.prop_motd=QLineEdit();self.prop_mode=QComboBox();self.prop_mode.addItems(['survival','creative','adventure','spectator'])
        self.prop_difficulty=QComboBox();self.prop_difficulty.addItems(['peaceful','easy','normal','hard'])
        self.prop_players=QSpinBox();self.prop_players.setRange(1,1000);self.prop_port=QSpinBox();self.prop_port.setRange(1,65535)
        self.prop_view=QSpinBox();self.prop_view.setRange(2,32);self.prop_sim=QSpinBox();self.prop_sim.setRange(2,32)
        self.prop_online=QCheckBox('Only verified Minecraft accounts can join');self.prop_whitelist=QCheckBox('Only whitelisted players can join');self.prop_pvp=QCheckBox('Players can damage each other')
        property_fields=[('Memory',self.manage_ram),('Java runtime',self.manage_java),('Server description',self.prop_motd),('Game mode',self.prop_mode),('Difficulty',self.prop_difficulty),('Maximum players',self.prop_players),('Server port',self.prop_port),('View distance',self.prop_view),('Simulation distance',self.prop_sim)]
        self.property_labels={}
        for row,(label,control) in enumerate(property_fields):
            label_widget=QLabel(label);self.property_labels[control]=label_widget;property_grid.addWidget(label_widget,row,0);control.setMinimumHeight(42);property_grid.addWidget(control,row,1)
        check_row=len(property_fields)
        for control in (self.prop_online,self.prop_whitelist,self.prop_pvp):property_grid.addWidget(control,check_row,1);check_row+=1
        self.auto_forward=QCheckBox('Advanced fallback: temporarily expose this server through my router (UPnP)')
        self.auto_forward.setToolTip('Requires verified accounts, an allow-list and confirmation for the exact port each app session. The ten-minute lease is renewed only while the server runs.')
        property_grid.addWidget(self.auto_forward,check_row,1);check_row+=1
        self.forward_help=QLabel('Recommended: connect Playit from the Share tab. It hides your home IP and leaves your router untouched. Direct UPnP can expose your public IP and is refused unless verified accounts and the allow-list are enabled, or if the router demands a permanent rule.')
        self.forward_help.setObjectName('muted');self.forward_help.setWordWrap(True);property_grid.addWidget(self.forward_help,check_row,1)
        check_row+=1
        playit_button=TextureButton('OPEN RECOMMENDED PLAYIT.GG GUIDE');playit_button.clicked.connect(lambda:self.show_page(5));property_grid.addWidget(playit_button,check_row,1)
        property_actions=QHBoxLayout();save_properties=TextureButton('SAVE SETTINGS');save_properties.setObjectName('primary');save_properties.clicked.connect(self.save_server_properties);property_actions.addWidget(save_properties);property_actions.addStretch();settings_layout.addLayout(property_actions);settings_layout.addStretch()
        doctor_page=QWidget();doctor_layout=QVBoxLayout(doctor_page);doctor_layout.setContentsMargins(16,16,16,16);doctor_layout.setSpacing(14);self.manage_sections.addTab(doctor_page,'Server Doctor')
        doctor_help=QLabel('Run a read-only check before launch or before sharing this server.');doctor_help.setObjectName('muted');doctor_help.setWordWrap(True);doctor_layout.addWidget(doctor_help)
        self.doctor_result=QPlainTextEdit();self.doctor_result.setObjectName('doctor');self.doctor_result.setReadOnly(True);self.doctor_result.setPlaceholderText('Choose Run server check to create a readiness report.');doctor_layout.addWidget(self.doctor_result,1)
        doctor_actions=QHBoxLayout();doctor_run=TextureButton('RUN SERVER CHECK');doctor_run.setObjectName('primary');doctor_run.clicked.connect(self.run_server_check);doctor_actions.addWidget(doctor_run)
        self.doctor_copy=TextureButton('Copy report');self.doctor_copy.setEnabled(False);self.doctor_copy.clicked.connect(self.copy_doctor_report);doctor_actions.addWidget(self.doctor_copy);doctor_actions.addStretch();doctor_layout.addLayout(doctor_actions)
        backup_page=QWidget();backup_layout=QVBoxLayout(backup_page);backup_layout.setContentsMargins(16,16,16,16);backup_layout.setSpacing(14);self.manage_sections.addTab(backup_page,'Backups')
        backup_help=QLabel('Create a backup before changing add-ons or important settings. Restoring keeps the current folder as a recovery copy.');backup_help.setObjectName('muted');backup_help.setWordWrap(True);backup_layout.addWidget(backup_help)
        backup_row=QHBoxLayout();self.backup_list=QComboBox();self.backup_list.setMinimumHeight(44);backup_row.addWidget(self.backup_list,1)
        backup_now=TextureButton('Back up now');backup_now.clicked.connect(self.create_backup);backup_row.addWidget(backup_now)
        restore=TextureButton('Restore selected');restore.clicked.connect(self.restore_backup);backup_row.addWidget(restore);backup_layout.addLayout(backup_row);backup_layout.addStretch()
        maintenance_scroll=QScrollArea();maintenance_scroll.setWidgetResizable(True);maintenance_scroll.setFrameShape(QFrame.NoFrame);maintenance_page=QWidget();maintenance_layout=QVBoxLayout(maintenance_page);maintenance_layout.setContentsMargins(16,16,16,16);maintenance_layout.setSpacing(14);maintenance_scroll.setWidget(maintenance_page);self.manage_sections.addTab(maintenance_scroll,'Maintenance')
        maintenance_title=QLabel('SERVER SOFTWARE UPDATES');maintenance_title.setObjectName('subheading');maintenance_layout.addWidget(maintenance_title)
        maintenance_help=QLabel('Check for a newer Vanilla, Fabric, Paper or Bedrock server build for this exact Minecraft version. Easy Realms will not upgrade the world to another Minecraft version.');maintenance_help.setObjectName('muted');maintenance_help.setWordWrap(True);maintenance_layout.addWidget(maintenance_help)
        self.update_result=QLabel('Choose Check for update.');self.update_result.setWordWrap(True);self.update_result.setMinimumHeight(70);self.update_result.setObjectName('updateResult');self.update_result.setContentsMargins(16,12,16,12);maintenance_layout.addWidget(self.update_result)
        safety_note=QLabel('Safety: the server must be stopped, the official download is verified where a checksum is published, and a full backup is created before any server software is replaced. Worlds, settings, add-ons and access lists are preserved.');safety_note.setObjectName('muted');safety_note.setWordWrap(True);maintenance_layout.addWidget(safety_note)
        maintenance_actions=QHBoxLayout();self.update_check=TextureButton('CHECK FOR UPDATE');self.update_check.clicked.connect(self.check_server_software_update);maintenance_actions.addWidget(self.update_check)
        self.update_install=TextureButton('BACK UP & INSTALL');self.update_install.setObjectName('primary');self.update_install.setEnabled(False);self.update_install.clicked.connect(self.install_server_software_update);maintenance_actions.addWidget(self.update_install);maintenance_actions.addStretch();maintenance_layout.addLayout(maintenance_actions)
        upgrade_line=QFrame();upgrade_line.setFrameShape(QFrame.HLine);maintenance_layout.addWidget(upgrade_line)
        upgrade_title=QLabel('MINECRAFT VERSION UPGRADE');upgrade_title.setObjectName('subheading');maintenance_layout.addWidget(upgrade_title)
        upgrade_help=QLabel('Move this server forward to a newer supported Minecraft release. Downgrades, Stable/Preview switching and unchecked add-ons are blocked. A full backup is always made first.');upgrade_help.setObjectName('muted');upgrade_help.setWordWrap(True);maintenance_layout.addWidget(upgrade_help)
        upgrade_row=QHBoxLayout();self.upgrade_version=QComboBox();self.upgrade_version.setMinimumHeight(44);self.upgrade_version.setPlaceholderText('Load newer versions');self.upgrade_version.currentIndexChanged.connect(self.reset_upgrade_plan);upgrade_row.addWidget(self.upgrade_version,1)
        self.upgrade_load=TextureButton('LOAD VERSIONS');self.upgrade_load.clicked.connect(self.load_upgrade_versions);upgrade_row.addWidget(self.upgrade_load)
        self.upgrade_check=TextureButton('CHECK UPGRADE');self.upgrade_check.setEnabled(False);self.upgrade_check.clicked.connect(self.check_server_version_upgrade);upgrade_row.addWidget(self.upgrade_check);maintenance_layout.addLayout(upgrade_row)
        self.upgrade_result=QLabel('Load the supported versions, then choose where you want to move this server.');self.upgrade_result.setWordWrap(True);self.upgrade_result.setMinimumHeight(80);self.upgrade_result.setObjectName('updateResult');self.upgrade_result.setContentsMargins(16,12,16,12);maintenance_layout.addWidget(self.upgrade_result)
        upgrade_actions=QHBoxLayout();self.upgrade_install=TextureButton('BACK UP & UPGRADE');self.upgrade_install.setObjectName('primary');self.upgrade_install.setEnabled(False);self.upgrade_install.clicked.connect(self.install_server_version_upgrade);upgrade_actions.addWidget(self.upgrade_install);upgrade_actions.addStretch();maintenance_layout.addLayout(upgrade_actions);maintenance_layout.addStretch()
        automation_page=QWidget();automation_layout=QVBoxLayout(automation_page);automation_layout.setContentsMargins(16,16,16,16);automation_layout.setSpacing(14);self.manage_sections.addTab(automation_page,'Automation')
        easy_title=QLabel('EASY MODE');easy_title.setObjectName('subheading');automation_layout.addWidget(easy_title)
        self.hardware_summary=QLabel('Detecting this PC…');self.hardware_summary.setObjectName('muted');self.hardware_summary.setWordWrap(True);automation_layout.addWidget(self.hardware_summary)
        self.host_and_play=QCheckBox('I will play Minecraft on this PC while it hosts the server');self.host_and_play.setChecked(True);automation_layout.addWidget(self.host_and_play)
        recommend_button=TextureButton('APPLY RECOMMENDED PERFORMANCE SETTINGS');recommend_button.setObjectName('primary');recommend_button.clicked.connect(self.apply_easy_mode);automation_layout.addWidget(recommend_button)
        automation_layout.addSpacing(8)
        self.auto_backup_launch=QCheckBox('Create a backup before each manual launch');automation_layout.addWidget(self.auto_backup_launch)
        retention_row=QHBoxLayout();retention_row.addWidget(QLabel('Keep newest automatic backups'));self.auto_backup_keep=QSpinBox();self.auto_backup_keep.setRange(1,20);self.auto_backup_keep.setValue(5);retention_row.addWidget(self.auto_backup_keep);retention_row.addStretch();automation_layout.addLayout(retention_row)
        self.auto_stop_empty=QCheckBox('Gracefully stop the server when nobody is online');automation_layout.addWidget(self.auto_stop_empty)
        idle_row=QHBoxLayout();idle_row.addWidget(QLabel('Wait before stopping'));self.auto_stop_minutes=QSpinBox();self.auto_stop_minutes.setRange(5,240);self.auto_stop_minutes.setValue(30);self.auto_stop_minutes.setSuffix(' minutes');idle_row.addWidget(self.auto_stop_minutes);idle_row.addStretch();automation_layout.addLayout(idle_row)
        self.auto_backup_launch.toggled.connect(self.auto_backup_keep.setEnabled);self.auto_backup_keep.setEnabled(False)
        self.auto_stop_empty.toggled.connect(self.auto_stop_minutes.setEnabled);self.auto_stop_minutes.setEnabled(False)
        self.auto_restart_crash=QCheckBox('Restart automatically after an unexpected crash');automation_layout.addWidget(self.auto_restart_crash)
        crash_note=QLabel('Crash recovery waits three seconds and stops after three attempts within ten minutes. Empty-server shutdown always uses Minecraft’s normal save-and-stop command.');crash_note.setObjectName('muted');crash_note.setWordWrap(True);automation_layout.addWidget(crash_note)
        automation_actions=QHBoxLayout();save_automation=TextureButton('SAVE AUTOMATION');save_automation.setObjectName('primary');save_automation.clicked.connect(self.save_automation);automation_actions.addWidget(save_automation);automation_actions.addStretch();automation_layout.addLayout(automation_actions);automation_layout.addStretch()
        self.pages.addWidget(manage)
        addons_page=QWidget();addons_layout=QVBoxLayout(addons_page);addons_layout.setContentsMargins(28,24,28,24);addons_layout.setSpacing(14)
        addons_title=QLabel('MODS & PLUGINS');addons_title.setObjectName('pageTitle');addons_layout.addWidget(addons_title)
        self.addon_context=QLabel('Choose a Fabric or Paper server from My servers.');self.addon_context.setWordWrap(True);addons_layout.addWidget(self.addon_context)
        addon_note=QLabel('Compatible results only • verified downloads • automatic required dependencies • stop the server before changes');addon_note.setObjectName('muted');addon_note.setWordWrap(True);addons_layout.addWidget(addon_note)
        self.addon_sections=QTabWidget();self.addon_sections.setObjectName('sections');addons_layout.addWidget(self.addon_sections,1)
        browse_page=QWidget();browse_layout=QVBoxLayout(browse_page);browse_layout.setContentsMargins(14,14,14,14);browse_layout.setSpacing(12);self.addon_sections.addTab(browse_page,'Browse Modrinth')
        addon_search_row=QHBoxLayout();self.addon_search=QLineEdit();self.addon_search.setPlaceholderText('Search mods or plugins');self.addon_search.setFixedHeight(46);self.addon_search.returnPressed.connect(self.search_addons);addon_search_row.addWidget(self.addon_search,1)
        self.addon_search_button=TextureButton('SEARCH');self.addon_search_button.setObjectName('primary');self.addon_search_button.setFixedHeight(50);self.addon_search_button.clicked.connect(self.search_addons);addon_search_row.addWidget(self.addon_search_button);browse_layout.addLayout(addon_search_row)
        self.preset_frame=QFrame();self.preset_frame.setObjectName('serverCard');preset_layout=QHBoxLayout(self.preset_frame);preset_layout.setContentsMargins(16,12,16,12)
        preset_copy=QVBoxLayout();preset_heading=QLabel('FABRIC PRESETS');preset_heading.setObjectName('smallHeading');preset_copy.addWidget(preset_heading);preset_note=QLabel('One-click starter packs with the same dependency and safety checks.');preset_note.setObjectName('muted');preset_copy.addWidget(preset_note);preset_layout.addLayout(preset_copy,1)
        for preset,projects in FABRIC_PRESETS.items():
            button=TextureButton(preset);button.clicked.connect(lambda checked=False,p=list(projects),n=preset:self.preview_addon_install(p,n));preset_layout.addWidget(button)
        browse_layout.addWidget(self.preset_frame)
        self.addon_results_scroll=QScrollArea();self.addon_results_scroll.setWidgetResizable(True);self.addon_results_scroll.setFrameShape(QFrame.NoFrame);self.addon_results_content=QWidget();self.addon_results=QVBoxLayout(self.addon_results_content);self.addon_results.setContentsMargins(0,4,4,4);self.addon_results.addStretch();self.addon_results_scroll.setWidget(self.addon_results_content);browse_layout.addWidget(self.addon_results_scroll,1)
        installed_page=QWidget();installed_layout=QVBoxLayout(installed_page);installed_layout.setContentsMargins(14,14,14,14);self.addon_sections.addTab(installed_page,'Installed')
        self.addon_installed_scroll=QScrollArea();self.addon_installed_scroll.setWidgetResizable(True);self.addon_installed_scroll.setFrameShape(QFrame.NoFrame);self.addon_installed_content=QWidget();self.addon_installed=QVBoxLayout(self.addon_installed_content);self.addon_installed.setContentsMargins(0,4,4,4);self.addon_installed.addStretch();self.addon_installed_scroll.setWidget(self.addon_installed_content);installed_layout.addWidget(self.addon_installed_scroll,1)
        self.pages.addWidget(addons_page)
        players_scroll=QScrollArea();players_scroll.setWidgetResizable(True);players_scroll.setFrameShape(QFrame.NoFrame);players_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        players_page=QWidget();players_layout=QVBoxLayout(players_page);players_layout.setContentsMargins(28,24,28,24);players_layout.setSpacing(14);players_layout.setSizeConstraint(QLayout.SetMinimumSize)
        players_title=QLabel('PLAYER ACCESS');players_title.setObjectName('pageTitle');players_layout.addWidget(players_title)
        self.player_context=QLabel('Choose a server from My servers.');self.player_context.setWordWrap(True);players_layout.addWidget(self.player_context)
        player_note=QLabel('Allow-list changes and operator permissions are sent through the selected server’s own console. Start the server before changing a player. Local access files are reviewed read-only.');player_note.setObjectName('muted');player_note.setWordWrap(True);players_layout.addWidget(player_note)
        access_card=QFrame();access_card.setObjectName('serverCard');access_layout=QVBoxLayout(access_card);access_layout.setContentsMargins(16,14,16,14);access_layout.setSpacing(10)
        access_heading=QLabel('TRUSTED PLAYERS');access_heading.setObjectName('smallHeading');access_layout.addWidget(access_heading)
        access_status_row=QHBoxLayout();self.player_allow_state=QLabel('Allow-list status unavailable');self.player_allow_state.setWordWrap(True);access_status_row.addWidget(self.player_allow_state,1)
        self.player_enable_allowlist=TextureButton('Enable allow-list');self.player_enable_allowlist.clicked.connect(self.enable_player_allowlist);access_status_row.addWidget(self.player_enable_allowlist);access_layout.addLayout(access_status_row)
        self.player_name=QLineEdit();self.player_name.setPlaceholderText('Java username or Bedrock Gamertag');self.player_name.setFixedHeight(46);self.player_name.returnPressed.connect(lambda:self.player_access_action('add'));access_layout.addWidget(self.player_name)
        access_buttons=QHBoxLayout();self.player_add=TextureButton('ADD TRUSTED PLAYER');self.player_add.setObjectName('primary');self.player_add.clicked.connect(lambda:self.player_access_action('add'));access_buttons.addWidget(self.player_add,1)
        self.player_remove=TextureButton('Remove access');self.player_remove.clicked.connect(lambda:self.player_access_action('remove'));access_buttons.addWidget(self.player_remove)
        self.player_show_server=TextureButton('Ask server for list');self.player_show_server.clicked.connect(lambda:self.player_access_action('list'));access_buttons.addWidget(self.player_show_server);access_layout.addLayout(access_buttons);players_layout.addWidget(access_card)
        operator_card=QFrame();operator_card.setObjectName('serverCard');operator_layout=QVBoxLayout(operator_card);operator_layout.setContentsMargins(16,14,16,14);operator_layout.setSpacing(10)
        operator_heading=QLabel('OPERATORS');operator_heading.setObjectName('smallHeading');operator_layout.addWidget(operator_heading)
        operator_warning=QLabel('Operators can run powerful commands and change the world. Grant this only to someone you completely trust.');operator_warning.setObjectName('muted');operator_warning.setWordWrap(True);operator_layout.addWidget(operator_warning)
        operator_buttons=QHBoxLayout();self.player_op=TextureButton('MAKE OPERATOR');self.player_op.clicked.connect(lambda:self.player_access_action('op'));operator_buttons.addWidget(self.player_op)
        self.player_deop=TextureButton('Remove operator');self.player_deop.clicked.connect(lambda:self.player_access_action('deop'));operator_buttons.addWidget(self.player_deop);operator_buttons.addStretch();operator_layout.addLayout(operator_buttons);players_layout.addWidget(operator_card)
        review_header=QHBoxLayout();review_title=QLabel('CURRENT LOCAL ACCESS FILES');review_title.setObjectName('smallHeading');review_header.addWidget(review_title);review_header.addStretch()
        refresh_players=TextureButton('Refresh');refresh_players.clicked.connect(self.refresh_players_page);review_header.addWidget(refresh_players)
        open_console=TextureButton('Open console');open_console.clicked.connect(lambda:self.show_page(2));review_header.addWidget(open_console);players_layout.addLayout(review_header)
        self.player_review=QPlainTextEdit();self.player_review.setReadOnly(True);self.player_review.setMinimumHeight(130);self.player_review.setPlaceholderText('Select a server to review its access list.');players_layout.addWidget(self.player_review)
        self.player_action_buttons=(self.player_add,self.player_remove,self.player_show_server,self.player_op,self.player_deop)
        players_scroll.setWidget(players_page);self.pages.addWidget(players_scroll)
        legal_page=QWidget();legal_layout=QVBoxLayout(legal_page);legal_layout.setContentsMargins(30,26,30,26);legal_layout.setSpacing(16)
        legal_title=QLabel('ABOUT & LEGAL');legal_title.setObjectName('pageTitle');legal_layout.addWidget(legal_title)
        legal_notice=QLabel(DISCLAIMER);legal_notice.setWordWrap(True);legal_notice.setStyleSheet('font-weight:bold;color:#f2c26f;font-size:15px;');legal_layout.addWidget(legal_notice)
        legal_copy=QLabel(f'Easy Realms is an independent, local-first community tool. This is {APP_VERSION}, so keep separate backups of important worlds and report problems with enough detail to reproduce them.');legal_copy.setWordWrap(True);legal_layout.addWidget(legal_copy)
        support_note=QLabel('Need to report a bug? Export a privacy-scrubbed support ZIP. It includes recent Easy Realms diagnostics and basic system details, but excludes worlds, settings, server console output, player lists, add-ons and account data. Nothing is uploaded automatically.');support_note.setObjectName('muted');support_note.setWordWrap(True);legal_layout.addWidget(support_note)
        legal_buttons=QGridLayout();legal_buttons.setHorizontalSpacing(12);legal_buttons.setVerticalSpacing(10);legal_buttons.setColumnStretch(0,1);legal_buttons.setColumnStretch(1,1)
        review_agreement=TextureButton('Review agreement');review_agreement.clicked.connect(self.review_agreement);legal_buttons.addWidget(review_agreement,0,0)
        minecraft_eula=TextureButton('Minecraft EULA');minecraft_eula.clicked.connect(lambda:QDesktopServices.openUrl(QUrl('https://www.minecraft.net/eula')));legal_buttons.addWidget(minecraft_eula,0,1)
        open_logs=TextureButton('Open diagnostic logs');open_logs.clicked.connect(self.open_logs_folder);legal_buttons.addWidget(open_logs,1,0)
        export_support=TextureButton('Export bug report');export_support.clicked.connect(self.export_support_bundle);legal_buttons.addWidget(export_support,1,1);legal_layout.addLayout(legal_buttons)
        legal_details=QTextBrowser();legal_details.setOpenExternalLinks(True);legal_details.setHtml(f'<h3>Privacy summary</h3><p>Easy Realms keeps its settings, logs and managed-server records in the local data folder. It does not automatically upload worlds, logs or personal files. Catalog, server, Java, add-on and tunnel requests go directly to the named external providers.</p><h3>Release information</h3><p>{APP_VERSION} • Agreement revision 2026-11-17-v1</p><p>See <b>PRIVACY.md</b>, <b>THIRD_PARTY_NOTICES.txt</b> and <b>RELEASE_NOTES.md</b> in the application files for more information.</p>');legal_layout.addWidget(legal_details,1)
        self.pages.addWidget(legal_page)
        self.bar=QProgressBar();self.bar.setFixedHeight(5);self.bar.setTextVisible(False);self.bar.setValue(0);main.addWidget(self.bar)
        self.status=QLabel('Connecting to official catalogs…');self.status.setObjectName('status');self.status.setWordWrap(True);self.status.setAlignment(Qt.AlignLeft|Qt.AlignVCenter);self.status.setMinimumHeight(42);self.status.setSizePolicy(QSizePolicy.Expanding,QSizePolicy.Minimum);main.addWidget(self.status)
        self.setStyleSheet('''
        QWidget {background:#242424;color:#ededed;font-family:"Minecraft Seven v2";font-size:14px;}
        QLabel {background:transparent;} QLabel#muted {color:#a5a5a5;font-size:12px;} QLabel#navCaption {color:#8f958d;font-size:11px;font-weight:bold;padding-top:4px;}
        QFrame#sidebar {background:#292929;border-right:1px solid #1b1b1b;}
        QFrame#selectionChip {background:#1d1d1d;border:1px solid #4b4b4b;border-left:3px solid #72c25b;}
        QLabel#selectionStatus {color:#d7ddd5;font-size:11px;}
        QLabel#brand {font-family:"Minecraft Ten";font-size:22px;}
        QLabel#navCaption,QLabel#section,QLabel#subheading,QLabel#smallHeading {font-family:"Minecraft Ten";font-weight:normal;}
        QLabel#section {font-size:16px;} QLabel#pageTitle {font-family:"Minecraft Ten";font-size:26px;}
        QLabel#subheading {font-size:19px;} QLabel#smallHeading {font-size:16px;}
        QPushButton {background:#3a3a3a;border:2px solid #1a1a1a;border-top-color:#686868;border-left-color:#5b5b5b;border-bottom-color:#171717;border-right-color:#171717;padding:8px 16px;border-radius:0;}
        QPushButton:focus {border:2px solid #9bdd84;}
        QPushButton:hover {background:#484848;border-top-color:#8b8b8b;border-left-color:#7a7a7a;border-bottom-color:#202020;border-right-color:#202020;}
        QPushButton:pressed {background:#292929;border-top-color:#151515;border-left-color:#151515;border-bottom-color:#686868;border-right-color:#5b5b5b;}
        QPushButton:disabled {color:#717171;background:#2c2c2c;border-color:#252525;border-top-color:#424242;border-left-color:#3b3b3b;}
        QPushButton#navMenu {background:#343434;text-align:left;border:2px solid #1c1c1c;border-top-color:#5b5b5b;border-left-color:#505050;padding:10px 14px;}
        QPushButton#navMenu:hover {background:#414141;border-top-color:#7a7a7a;border-left-color:#6c6c6c;border-bottom-color:#72c25b;}
        QFrame#dropdownPanel {background:#1c1c1c;border-left:2px solid #4f9846;border-right:1px solid #383838;border-bottom:1px solid #383838;}
        QPushButton#dropdownItem {background:#252525;text-align:left;border:0;border-left:3px solid transparent;border-bottom:1px solid #353535;padding:7px 10px;}
        QPushButton#dropdownItem:hover {background:#353f33;border-left:3px solid #79ca63;}
        QPushButton#dropdownItem:pressed {background:#202b1f;}
        QPushButton#tab {background:transparent;border:0;border-bottom:3px solid transparent;font-size:15px;padding:8px 9px;min-height:34px;}
        QPushButton#tab:hover {background:#2c2c2c;border-bottom-color:#555b54;}
        QPushButton#tab:checked {border-bottom-color:#6db55b;font-weight:bold;}
        QPushButton#tab:disabled {background:transparent;border-bottom-color:transparent;}
        QPushButton#primary {font-family:"Minecraft Ten";font-size:24px;background:#3c8b42;border:3px solid #18421f;border-top-color:#8bd379;border-left-color:#69b85c;border-bottom:5px solid #15391b;border-right-color:#15391b;border-radius:0;}
        QPushButton#primary:hover {background:#489d4f;border-top-color:#a2e493;border-left-color:#80cf72;border-bottom-color:#1b4922;border-right-color:#1b4922;}
        QPushButton#primary:pressed {background:#317438;border-top-color:#15391b;border-left-color:#15391b;border-bottom:3px solid #78c96a;border-right-color:#5dac52;}
        QPushButton#primary:disabled {background:#364335;color:#7f8b7b;border-color:#283127;border-top-color:#4b5949;border-left-color:#454f43;}
        QLabel#heroTitle {font-family:"Minecraft Ten";font-size:48px;color:white;}
        QLabel#heroSubtitle {font-size:20px;color:white;} QLabel#heroCaption {font-family:"Minecraft Ten";font-size:20px;color:white;}
        QFrame#dock {background:#292929;border-top:1px solid #3d3d3d;} QFrame#info {background:#303030;border-top:1px solid #3c3c3c;}
        QLabel#createState {background:#292929;color:#c3c8c1;border-left:3px solid #70756e;padding:10px 12px;}
        QLabel#createState[state="ready"] {background:#293827;color:#b8e7ad;border-left-color:#79ca63;}
        QLabel#createState[state="warning"] {background:#3b3324;color:#f0cf91;border-left-color:#d4a64f;}
        QFrame#serverCard {background:#303030;border:1px solid #444;border-radius:0;}
        QFrame#serverCard[selected="true"] {background:#313a2f;border:1px solid #72c25b;}
        QLabel#serverBadge {background:#252525;color:#aeb3ac;border:1px solid #4a4d49;padding:6px 8px;border-radius:0;font-size:11px;}
        QLabel#serverBadge[state="selected"] {background:#354133;color:#bce8b1;border-color:#72c25b;}
        QLabel#serverBadge[state="running"] {background:#275c2d;color:white;border-color:#86dc71;}
        QLabel#updateResult {background:#303030;border:1px solid #444;border-radius:4px;}
        QFrame#performancePanel {background:#2d2d2d;border:1px solid #444;border-radius:4px;}
        QLabel#metricValue {font-size:18px;font-weight:bold;color:#ededed;}
        QLabel#metricCaption {font-size:10px;color:#9fa59e;}
        QLineEdit,QComboBox,QSpinBox {background:#171717;border:1px solid #646464;padding:6px 10px;min-height:28px;}
        QLineEdit:focus,QComboBox:focus,QSpinBox:focus {border-color:#8fd777;}
        QComboBox QAbstractItemView {background:#292929;selection-background-color:#41683b;}
        QCheckBox::indicator {width:18px;height:18px;border:1px solid #929292;background:#171717;}
        QCheckBox::indicator:checked {background:#72c25b;border:2px solid #b2e6a1;}
        QPlainTextEdit {background:#161616;border:1px solid #454545;font-family:"Minecraft Seven v2";font-size:12px;}
        QTabWidget#sections::pane {border:1px solid #414141;background:#292929;top:-1px;}
        QTabWidget#sections QTabBar::tab {background:#292929;color:#bdbdbd;border:1px solid #414141;padding:10px 18px;min-width:110px;}
        QTabWidget#sections QTabBar::tab:selected {background:#353535;color:#ededed;border-top:2px solid #78c961;}
        QMenu {background:#303030;border:1px solid #555;padding:6px;} QMenu::item {padding:8px 24px;} QMenu::item:selected {background:#41683b;}
        QLabel#status {padding:8px 20px;color:#c5c5c5;font-size:12px;background:#202020;border-top:1px solid #383838;}
        QProgressBar {background:#202020;border:0;} QProgressBar::chunk {background:#72c25b;}
        QScrollBar:vertical {background:#202020;width:12px;} QScrollBar::handle:vertical {background:#606060;min-height:32px;}
        ''')
        # Give glyphs breathing room on both Windows and Linux font engines.
        for label in self.findChildren(QLabel):
            label.setContentsMargins(0,3,0,3)
            label.setMinimumHeight(max(label.minimumHeight(),label.fontMetrics().height()+8))
        self._prepare_page_transitions()
        memory=total_memory_gb();self.hardware_summary.setText(f'This PC has about {memory:.1f} GB of memory. Easy Mode keeps enough available for Windows'+(' and Minecraft.' if self.host_and_play.isChecked() else '.'))
        self.catalog=Catalog(self.contact.text());self.refresh_library();self.show_page(6 if self.library.all() else 0);self.update_create();self.update_kind_fields();self._update_navigation()
        for i,widget in enumerate([self.software_selector.header,self.library_selector.header,*self.tabs]):
            effect=QGraphicsOpacityEffect(widget);widget.setGraphicsEffect(effect);effect.setOpacity(0)
            anim=QPropertyAnimation(effect,b'opacity',self);anim.setDuration(400);anim.setStartValue(0);anim.setEndValue(1);anim.setEasingCurve(QEasingCurve.OutCubic)
            self.animations.append(anim);QTimer.singleShot(50+i*65,anim.start)
        self._startup_started=False

    def ensure_agreement(self):
        if agreement_is_current(self.settings):return True
        dialog=AgreementDialog(self)
        if not dialog.accepted_agreement():return False
        record_acceptance(self.settings);return True

    def review_agreement(self):
        AgreementDialog(self,review_only=True).exec()

    def open_logs_folder(self):
        logs=self.data/'logs';logs.mkdir(parents=True,exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(logs)))

    def export_support_bundle(self):
        if DIAGNOSTICS is not None:DIAGNOSTICS.flush()
        desktop=Path.home()/'Desktop';folder=desktop if desktop.is_dir() else Path.home()
        suggested=folder/f'Easy-Realms-Support-{time.strftime("%Y%m%d-%H%M%S")}.zip'
        destination,_=QFileDialog.getSaveFileName(self,'Save privacy-scrubbed bug report',str(suggested),'ZIP archive (*.zip)')
        if not destination:return
        try:archive=create_support_bundle(self.data,Path(destination),APP_VERSION,self.doctor_report)
        except Exception as exc:
            log_exception('Support bundle export failed',exc);self.error('Could not create the bug report ZIP: '+str(exc));return
        self.status.setText('Bug report ZIP created. Nothing was uploaded. Review it before sharing.')
        QMessageBox.information(self,'Bug report ready',f'Saved to:\n{archive}\n\nNothing was uploaded. Review the ZIP before sharing it with a bug report.')

    def begin_startup(self):
        if self._startup_started:return
        self._startup_started=True;QTimer.singleShot(50,self.load_versions)

    def navigate(self,index):
        if index==7:
            if self.selected_entry:self.open_manager(self.selected_entry)
            else:self.show_page(6);self.status.setText('Choose a server before opening Manage.')
            return
        if index==9 and not self.selected_entry:
            self.show_page(6);self.status.setText('Choose a server before managing players.');return
        if index==5:
            self.refresh_playit_target();self.refresh_playit_status()
        self.show_page(index)

    def refresh_playit_target(self):
        if not self.selected_entry:
            self.playit_page.set_target(None);return
        try:
            target=tunnel_target(self.selected_entry.kind,read_properties(self.selected_entry.path))
            self.playit_page.set_target(target,self.selected_entry.name)
        except Exception as exc:
            self.playit_page.set_target(None);self.playit_page.setup_status.setText(str(exc))

    def refresh_playit_status(self):
        self.refresh_playit_target();self.playit_page.agent_status.setText('Checking the Playit service…');self.playit_page.check_button.setEnabled(False)
        def complete(status):
            self.playit_page.set_agent_status(status);self.playit_page.check_button.setEnabled(True)
        self.job(lambda _:check_playit_status(),complete,lambda message:(self.playit_page.agent_status.setText(message),self.playit_page.check_button.setEnabled(True)))

    def start_playit_setup(self):
        if self.playit_process.state()!=QProcess.NotRunning:return
        executable=find_playit_executable()
        if executable is None:
            self.playit_page.setup_status.setText('Install Playit with the official Windows installer, then choose Check status. For safety, Easy Realms does not run standalone copies from Downloads or other user-writable folders.')
            QDesktopServices.openUrl(QUrl(PLAYIT_DOWNLOAD_URL));return
        self.playit_cancel_message='';self.playit_page.set_setup_active(True,'Starting Playit’s approval flow… Playit itself will open the one-time browser page. Check that it begins https://playit.gg/claim/ and never share it.')
        self.playit_process.setProgram(str(executable));self.playit_process.setArguments(['setup']);self.playit_process.start()
        self.playit_setup_timer.start()

    def playit_setup_finished(self,exit_code=0,exit_status=None):
        self.playit_setup_timer.stop()
        if self.playit_cancel_message:
            message=self.playit_cancel_message;self.playit_cancel_message='';self.playit_page.set_setup_active(False,message);return
        self.playit_page.set_setup_active(False)
        if exit_code==0:
            self.playit_page.setup_status.setText('Playit is connected. Create or review the selected server tunnel in the dashboard.')
            self.refresh_playit_status();QDesktopServices.openUrl(QUrl(PLAYIT_DASHBOARD_URL))
        else:
            self.playit_page.setup_status.setText('Playit setup did not finish. Check status and try again, or use the official Playit app.')

    def playit_setup_error(self,error):
        self.playit_setup_timer.stop()
        if self.playit_cancel_message:return
        self.playit_page.set_setup_active(False,'Playit could not start. Reinstall it from the official download and try again.')

    def cancel_playit_setup(self):
        self.playit_setup_timer.stop();self.playit_cancel_message='Playit setup was cancelled. No router changes were made.'
        if self.playit_process.state()!=QProcess.NotRunning:
            self.playit_process.terminate()
            if not self.playit_process.waitForFinished(2000):self.playit_process.kill()
        else:
            message=self.playit_cancel_message;self.playit_cancel_message='';self.playit_page.set_setup_active(False,message)

    def playit_setup_timeout(self):
        self.playit_cancel_message='Playit setup timed out after ten minutes and was stopped. Start again when you are ready to approve it.'
        if self.playit_process.state()!=QProcess.NotRunning:
            self.playit_process.terminate()
            if not self.playit_process.waitForFinished(2000):self.playit_process.kill()
        else:
            message=self.playit_cancel_message;self.playit_cancel_message='';self.playit_page.set_setup_active(False,message)

    def _selected_server_running(self):
        return bool(
            self.selected_entry
            and self.running_server
            and Path(self.selected_entry.path)==Path(self.running_server)
            and self.process.state()==QProcess.Running
            and self.server_started
        )

    def refresh_players_page(self):
        if not self.selected_entry:
            self.player_context.setText('Choose a server from My servers.')
            self.player_allow_state.setText('Allow-list status unavailable')
            self.player_review.clear();self.player_name.setEnabled(False);self.player_enable_allowlist.setEnabled(False)
            for button in self.player_action_buttons:button.setEnabled(False)
            return
        entry=self.selected_entry;kind=entry.kind;properties=read_properties(entry.path)
        allow_key='allow-list' if kind=='Bedrock' else 'white-list';enabled=str(properties.get(allow_key,'false')).lower()=='true'
        running=self._selected_server_running();state='running and ready' if running else 'stopped or still starting'
        self.player_context.setText(f'{entry.name} • {kind} {entry.version} • Server is {state}.')
        self.player_allow_state.setText('Allow-list is ON — only added players can join.' if enabled else 'Allow-list is OFF — anyone with the public address may try to join.')
        self.player_allow_state.setStyleSheet('color:#9bdd84;' if enabled else 'color:#f2b36f;')
        self.player_enable_allowlist.setEnabled(not enabled);self.player_enable_allowlist.setText('Allow-list enabled' if enabled else 'Enable allow-list')
        self.player_name.setEnabled(True);self.player_name.setPlaceholderText('Bedrock Gamertag (spaces allowed)' if kind=='Bedrock' else 'Java username (3–16 letters, numbers or _)')
        for button in self.player_action_buttons:button.setEnabled(running)
        try:
            snapshot=load_access_snapshot(entry.path,kind)
            lines=['ALLOWED PLAYERS']
            if snapshot.allowed:lines.extend('• '+name for name in snapshot.allowed)
            else:lines.append('(none recorded yet)')
            lines.extend(['','OPERATORS'])
            if kind=='Bedrock':lines.append('(review operator changes through the running server)')
            elif snapshot.operators:lines.extend('• '+name for name in snapshot.operators)
            else:lines.append('(none recorded yet)')
            if snapshot.note:lines.extend(['',snapshot.note])
            if not running:lines.extend(['','Start this server to add, remove, promote or demote players.'])
            self.player_review.setPlainText('\n'.join(lines))
        except PlayerAccessError as exc:
            self.player_review.setPlainText(str(exc)+'\n\nEasy Realms did not change the file. Use the running server console to inspect it.')

    def enable_player_allowlist(self):
        if not self.selected_entry:self.error('Choose a server first.');return
        kind=self.selected_entry.kind;key='allow-list' if kind=='Bedrock' else 'white-list'
        try:update_properties(self.selected_entry.path,{key:'true'})
        except Exception as exc:self.error(str(exc));return
        if self._selected_server_running():
            for command in player_commands(kind,'enable'):
                if not self._write_server_command(command):return
        self.prop_whitelist.setChecked(True)
        self.status.setText('Player allow-list enabled. Add each trusted friend before sharing the address.')
        self.refresh_players_page()

    def player_access_action(self,action):
        if not self.selected_entry:self.error('Choose a server first.');return
        if not self._selected_server_running():self.error('Start this selected server and wait until it is ready before changing players.');return
        kind=self.selected_entry.kind;name=''
        if action!='list':
            try:name=validate_player_name(kind,self.player_name.text())
            except PlayerAccessError as exc:self.error(str(exc));return
        if action=='op':
            answer=QMessageBox.warning(self,'Grant operator access?',f'{name} will be able to run powerful server commands and change the world. Only continue if you completely trust this player.',QMessageBox.Yes|QMessageBox.Cancel,QMessageBox.Cancel)
            if answer!=QMessageBox.Yes:return
        if action=='remove':
            answer=QMessageBox.question(self,'Remove player access?',f'Remove {name} from the allow-list and revoke operator access first?',QMessageBox.Yes|QMessageBox.Cancel,QMessageBox.Cancel)
            if answer!=QMessageBox.Yes:return
        if action=='add':
            key='allow-list' if kind=='Bedrock' else 'white-list'
            try:update_properties(self.selected_entry.path,{key:'true'})
            except Exception as exc:self.error(str(exc));return
            self.prop_whitelist.setChecked(True)
        try:commands=player_commands(kind,action,name)
        except PlayerAccessError as exc:self.error(str(exc));return
        for command in commands:
            if not self._write_server_command(command):return
        descriptions={'add':f'Adding {name} to trusted players…','remove':f'Removing {name} from server access…','op':f'Granting operator access to {name}…','deop':f'Removing operator access from {name}…','list':'The running server will print its allow-list in Console.'}
        self.status.setText(descriptions[action])
        if action!='list':self.player_name.clear();QTimer.singleShot(900,self.refresh_players_page)

    def _update_navigation(self):
        selected=self.selected_entry is not None
        self.tabs_by_page[7].setEnabled(selected)
        self.tabs_by_page[2].setEnabled(selected)
        self.tabs_by_page[9].setEnabled(selected)
        self.tabs_by_page[8].setEnabled(selected and self.selected_entry.kind in ('Fabric','Paper'))
        disabled_help='Choose a server from My servers first.'
        self.tabs_by_page[7].setToolTip('Manage the selected server' if selected else disabled_help)
        self.tabs_by_page[2].setToolTip('Open the selected server console' if selected else disabled_help)
        self.tabs_by_page[9].setToolTip('Manage trusted players and operators' if selected else disabled_help)
        addon_ready=selected and self.selected_entry.kind in ('Fabric','Paper')
        self.tabs_by_page[8].setToolTip('Browse compatible mods or plugins' if addon_ready else 'Select a Fabric or Paper server to manage add-ons.')
        self._update_selection_banner()

    @staticmethod
    def _set_widget_state(widget,name,value):
        if widget.property(name)==value:return
        widget.setProperty(name,value);widget.style().unpolish(widget);widget.style().polish(widget);widget.update()

    def _update_selection_banner(self):
        if not self.selected_entry:
            self.selection_status.setText('NO SERVER SELECTED');self.selection_status.setToolTip('Choose a server to unlock Manage, Console, Players and Add-ons.')
            self.selection_action.setText('CHOOSE');self.selection_action.setEnabled(True);self.selection_action.setToolTip('Open My servers')
            return
        same_running=bool(self.running_server and Path(self.selected_entry.path)==Path(self.running_server))
        if same_running and self.recovery_pending:
            state='RESTARTING';detail='World saved; starting again'
        elif same_running and self.process.state()==QProcess.Running:
            state='RUNNING';detail='Server is online'
        elif same_running and self.process.state()==QProcess.Starting:
            state='STARTING';detail='Please wait'
        else:
            state='SELECTED';detail='Ready to manage or launch'
        entry=self.selected_entry
        self.selection_status.setText(f'{state}  •  {entry.name}')
        self.selection_status.setToolTip(f'{entry.name} • {entry.kind} {entry.version} • {detail}')
        locked=self.process.state()!=QProcess.NotRunning or self.recovery_pending
        self.selection_action.setText('CHANGE');self.selection_action.setEnabled(not locked)
        self.selection_action.setToolTip('Stop the running server before switching.' if locked else 'Return to My servers')

    def _prepare_page_transitions(self):
        self._page_effects=[]
        for page_index in range(self.pages.count()):
            effect=QGraphicsOpacityEffect(self.pages.widget(page_index));effect.setOpacity(1.0 if page_index==self.pages.currentIndex() else 0.0)
            self.pages.widget(page_index).setGraphicsEffect(effect);self._page_effects.append(effect)
        self._page_transition=None;self._pending_page_index=None

    def _transition_to_page(self,index):
        if not 0<=index<self.pages.count():return
        if self._page_transition is not None:
            self._pending_page_index=index;return
        previous=self.pages.currentIndex()
        if previous==index:
            self._page_effects[index].setOpacity(1.0);return
        previous_effect=self._page_effects[previous];next_effect=self._page_effects[index]
        previous_effect.setOpacity(1.0);next_effect.setOpacity(0.0)
        target=self.pages.widget(index);finish_position=target.pos();target.move(finish_position+QPoint(18,0))
        self.pages.setCurrentIndex(index)
        group=QParallelAnimationGroup(self)
        fade=QPropertyAnimation(next_effect,b'opacity',group);fade.setDuration(190);fade.setStartValue(0.0);fade.setEndValue(1.0);fade.setEasingCurve(QEasingCurve.OutCubic)
        slide=QPropertyAnimation(target,b'pos',group);slide.setDuration(220);slide.setStartValue(target.pos());slide.setEndValue(finish_position);slide.setEasingCurve(QEasingCurve.OutCubic)
        group.addAnimation(fade);group.addAnimation(slide)
        self._page_transition=group
        group.finished.connect(lambda old=previous,new=index,animation=group:self._finish_page_transition(old,new,animation))
        group.start()

    def _finish_page_transition(self,previous,index,animation):
        self._page_effects[previous].setOpacity(0.0);self._page_effects[index].setOpacity(1.0)
        animation.deleteLater();self._page_transition=None
        pending=self._pending_page_index;self._pending_page_index=None
        if pending is not None and pending!=self.pages.currentIndex():self._transition_to_page(pending)

    def show_page(self,index):
        if index==6:self.refresh_library()
        if index==8:self.refresh_addons_page()
        if index==9:self.refresh_players_page()
        self._transition_to_page(index)
        active=0 if index==1 else index
        for i,b in enumerate(self.tabs):b.setChecked(self.tab_pages[i]==active)
        if index==1:self.config_detail.setText(self.detail.text())
        if index==2:self.server_label.setText(str(self.server) if self.server else 'Create or open a server to begin.')

    def job(self, fn, done, failed=None):
        worker = Worker(fn); self.jobs.append(worker)
        worker.result.connect(done); worker.failed.connect(failed or self.error)
        worker.progress.connect(lambda value,text:(self.bar.setValue(value),self.status.setText(text)))
        worker.finished.connect(lambda:self.jobs.remove(worker)); worker.start()

    def error(self,message):
        log_warning('User-visible error: %s',message)
        self.status.setText(message); self.console.appendPlainText(message)

    def contact_changed(self):
        self.settings.setValue('contact',self.contact.text().strip())
        if self.kind=='Paper': self.load_versions()

    def select_kind(self,kind):
        self.kind=kind
        self.section_title.setText('MINECRAFT: '+kind.upper()+' SERVER')
        self.software_selector.set_label(kind)
        self.update_kind_fields()
        self.load_versions()
        self.show_page(0)

    def update_kind_fields(self):
        paper=self.kind=='Paper';bedrock=self.kind=='Bedrock'
        self.contact.setVisible(paper);self.form_rows[4].setVisible(paper);self.form_labels[4].setVisible(paper)
        for index in (1,3):self.form_rows[index].setVisible(not bedrock);self.form_labels[index].setVisible(not bedrock)
        if bedrock:self.setup_tip.setText('Bedrock runs natively on 64-bit Windows and does not use Java. Easy Realms downloads and checks the official ZIP from minecraft.net.')
        else:self.setup_tip.setText('Java set to Automatic downloads the required runtime into data/java when needed. Paper requires a contact URL or email for its download API.')

    def load_versions(self):
        if self.creating: return
        self.generation+=1; token=self.generation; kind=self.kind
        self.catalog_loading=True;self.spec=None;self.update_create();self.version.setEnabled(False);self.version.setPlaceholderText('Loading versions…');self.refresh.setEnabled(False);self.version.blockSignals(True);self.version.clear();self.version.blockSignals(False)
        self.catalog=Catalog(self.contact.text()); catalog=self.catalog
        self.detail.setText('Fetching supported release versions…'); self.status.setText(f'Loading {kind} catalog…')
        if self.offline:
            self.catalog_loading=False;self.version.setPlaceholderText('Preview mode');self.refresh.setEnabled(True);self.detail.setText('Preview mode • live network disabled');self.config_detail.setText(self.detail.text());self.status.setText('Preview only');self.update_create();return
        def done(versions):
            if token!=self.generation:return
            self.catalog_loading=False;self.refresh.setEnabled(True);self.version.setEnabled(bool(versions));self.version.setPlaceholderText('No versions available' if not versions else 'Choose a version')
            self.version.blockSignals(True); self.version.addItems(versions); self.version.blockSignals(False)
            if versions:self.resolve(versions[0])
            else:
                self.detail.setText('No supported versions are currently available. Try Refresh or import an existing server.');self.config_detail.setText(self.detail.text());self.status.setText(f'No supported {kind} versions are available right now.');self.update_create()
        def failed(message):
            if token!=self.generation:return
            self.catalog_loading=False;self.refresh.setEnabled(True);self.version.setEnabled(False);self.version.setPlaceholderText('Versions unavailable');self.detail.setText('Catalog unavailable. Check your connection, try Refresh, or import an existing server.');self.config_detail.setText(self.detail.text());self.status.setText(f'{kind} versions could not be loaded. Try Refresh.');self.console.appendPlainText('[Easy Realms] '+message);self.update_create()
        self.job(lambda _:catalog.versions(kind),done,failed)

    def resolve(self,version):
        if not version:return
        self.generation+=1; token=self.generation; kind=self.kind; catalog=self.catalog
        self.spec=None; self.update_create(); self.detail.setText('Checking compatible server build…')
        def done(spec):
            if token!=self.generation:return
            self.spec=spec
            if kind=='Bedrock':
                preview_note='  •  Experimental: use a separate world' if version.startswith('Preview ') else ''
                self.detail.setText(f"Bedrock {version}  •  {spec['detail']}{preview_note}")
            else:
                build_detail='' if spec['detail']==version else spec['detail']+'  •  ';self.detail.setText(f"{kind} {version}  •  {build_detail}Requires Java {spec['java']}")
            self.config_detail.setText(self.detail.text()); self.status.setText('Ready to configure.'); self.update_create()
        def failed(message):
            if token==self.generation:self.detail.setText(message);self.config_detail.setText(message);self.status.setText('Choose another version or refresh.')
        self.job(lambda _:catalog.resolve(kind,version),done,failed)

    def update_create(self):
        guidance=creation_guidance(self.kind,self.version.currentText().strip(),bool(self.spec),self.catalog_loading,self.creating,self.eula.isChecked(),self.name.text(),self.folder.text())
        self.setup.setEnabled(guidance.can_configure)
        self.setup.setToolTip('Continue to server settings' if guidance.can_configure else 'Wait for a compatible Minecraft version to finish loading')
        self.create.setEnabled(guidance.can_create)
        self.create_state.setText(guidance.message);self._set_widget_state(self.create_state,'state',guidance.state)

    def choose_folder(self):
        path=QFileDialog.getExistingDirectory(self,'Choose parent folder',self.folder.text())
        if path:self.folder.setText(path)
    def choose_java(self):
        path,_=QFileDialog.getOpenFileName(self,'Select java.exe (Windows) or java')
        if path:self.java.setText(path)
    def build(self):
        spec=dict(self.spec); parent=self.folder.text(); name=self.name.text().strip(); ram=self.ram.value(); java=self.java.text().strip(); accepted=self.eula.isChecked(); catalog=self.catalog
        self.settings.setValue('java',java); self.cancel.clear(); self.creating=True; self.busy(True)
        def done(path):
            self.server=Path(path);self.selected_entry=self.library.add(path);self.refresh_library(); self.creating=False; self.busy(False); self.launch.setEnabled(self.process.state()==QProcess.NotRunning);self._update_navigation(); self.status.setText(f'Created {path}'); self.show_page(2)
        def failed(message):
            self.creating=False; self.busy(False); self.error(message)
        self.job(lambda progress:create_server(catalog,spec,parent,name,ram,java,accepted,progress,self.cancel),done,failed)

    def busy(self,busy):
        self.panel.setEnabled(not busy); self.version.setEnabled(not busy); self.refresh.setEnabled(not busy)
        self.software_selector.setEnabled(not busy)
        self.eula.setEnabled(not busy); self.abort.setEnabled(busy); self.update_create()

    def open_existing(self):
        if self.creating or self.process.state()!=QProcess.NotRunning:return
        path=QFileDialog.getExistingDirectory(self,'Choose the Minecraft server folder')
        if path:
            try:
                entry=self.library.add(path);self._ensure_launch_info(entry);self.select_server(entry,2);self.refresh_library();self.status.setText(f'Imported {entry.name}. Its world files stayed exactly where they were.')
            except Exception as exc:self.error(str(exc))

    def _ensure_launch_info(self,entry):
        folder=Path(entry.path);file=folder/'easyservers.json'
        if file.is_file():return
        if entry.kind=='Bedrock':
            executable='bedrock_server.exe' if (folder/'bedrock_server.exe').is_file() else 'bedrock_server'
            if not (folder/executable).is_file():raise ValueError('No Bedrock server executable was found in that folder.')
            config={'name':entry.name,'kind':'Bedrock','version':entry.version,'ram':0,'executable':executable}
            temp=file.with_suffix('.tmp');temp.write_text(json.dumps(config,indent=2),encoding='utf-8');os.replace(temp,file);return
        jars=sorted(folder.glob('*.jar'),key=lambda item:(item.name.lower()!='server.jar',item.name.lower()))
        if not jars:raise ValueError('No server JAR was found in that folder.')
        java=self.settings.value('java','java')
        if not java or str(java).lower()=='automatic':java='java'
        config={'name':entry.name,'kind':entry.kind,'version':entry.version,'java':str(java),'ram':4,'jar':jars[0].name}
        temp=file.with_suffix('.tmp');temp.write_text(json.dumps(config,indent=2),encoding='utf-8');os.replace(temp,file)

    def refresh_library(self):
        while self.library_rows.count()>1:
            item=self.library_rows.takeAt(0)
            if item.widget():item.widget().deleteLater()
            elif item.layout():
                while item.layout().count():
                    child=item.layout().takeAt(0)
                    if child.widget():child.widget().deleteLater()
        entries=self.library.all()
        if not entries:
            empty=QFrame();empty.setObjectName('info');layout=QVBoxLayout(empty);layout.setContentsMargins(24,24,24,24)
            title=QLabel('LET’S MAKE YOUR FIRST SERVER');title.setObjectName('subheading');layout.addWidget(title)
            copy=QLabel('Start from an official Vanilla, Fabric, Paper or Bedrock download, or safely add a server folder you already use. Importing never moves or deletes the world.');copy.setObjectName('muted');copy.setWordWrap(True);layout.addWidget(copy)
            empty_actions=QHBoxLayout();create_first=TextureButton('CREATE A SERVER');create_first.setObjectName('primary');create_first.clicked.connect(lambda:self.show_page(0));empty_actions.addWidget(create_first)
            import_first=TextureButton('Import existing');import_first.clicked.connect(self.open_existing);empty_actions.addWidget(import_first);empty_actions.addStretch();layout.addLayout(empty_actions)
            self.library_rows.insertWidget(0,empty);return
        for entry in entries:
            selected=bool(self.selected_entry and self.selected_entry.id==entry.id)
            running=bool(self.running_server and Path(entry.path)==Path(self.running_server) and self.process.state()==QProcess.Running)
            card=QFrame();card.setObjectName('serverCard');card.setProperty('selected',selected);row=QHBoxLayout(card);row.setContentsMargins(18,14,18,14);row.setSpacing(12)
            text=QVBoxLayout();name=QLabel(entry.name);name.setObjectName('subheading');text.addWidget(name)
            details=QLabel(f'{entry.kind} • Minecraft {entry.version} • {entry.path}');details.setObjectName('muted');details.setWordWrap(True);text.addWidget(details);row.addLayout(text,1)
            badge=QLabel('RUNNING' if running else 'SELECTED' if selected else 'READY');badge.setObjectName('serverBadge');badge.setProperty('state','running' if running else 'selected' if selected else 'ready');badge.setAlignment(Qt.AlignCenter);badge.setMinimumWidth(78);badge.setToolTip('This server is running now' if running else 'This is the active server' if selected else 'Select this server to manage or launch it');row.addWidget(badge)
            open_button=TextureButton('Open console');open_button.clicked.connect(lambda checked=False,item=entry:self.select_server(item,2));row.addWidget(open_button)
            manage_button=TextureButton('Manage');manage_button.clicked.connect(lambda checked=False,item=entry:self.open_manager(item));row.addWidget(manage_button)
            more_button=TextureButton('More');more_menu=QMenu(more_button)
            more_menu.addAction('Manage players',lambda checked=False,item=entry:self.select_server(item,9))
            if entry.kind in ('Fabric','Paper'):more_menu.addAction('Manage add-ons',lambda checked=False,item=entry:self.select_server(item,8));more_menu.addSeparator()
            more_menu.addAction('Open folder',lambda checked=False,item=entry:QDesktopServices.openUrl(QUrl.fromLocalFile(item.path)))
            more_menu.addAction('Forget server',lambda checked=False,item=entry:self.forget_server(item));more_button.setMenu(more_menu);row.addWidget(more_button)
            self.library_rows.insertWidget(self.library_rows.count()-1,card)

    def select_server(self,entry,page=2):
        if (self.process.state()!=QProcess.NotRunning or self.recovery_pending) and self.running_server and Path(entry.path)!=self.running_server:
            self.error('Stop the running server before switching to another one.');return
        try:self._ensure_launch_info(entry)
        except Exception as exc:self.error(str(exc));return
        self.selected_entry=entry;self.server=Path(entry.path);self.launch.setEnabled(self.process.state()==QProcess.NotRunning);self.server_label.setText(f'{entry.name} • {entry.kind} {entry.version}\n{entry.path}');self.section_title.setText(entry.name.upper()+'  •  '+entry.kind.upper());self._update_navigation();self.status.setText(f'{entry.name} is ready.');self.show_page(page)

    def forget_server(self,entry):
        if self.server and Path(entry.path)==self.server and self.process.state()!=QProcess.NotRunning:
            self.error('Stop this server before removing it from the list.');return
        self.library.remove(entry.id)
        if self.selected_entry and self.selected_entry.id==entry.id:self.selected_entry=None;self.server=None;self.launch.setEnabled(False);self.section_title.setText('EASY REALMS');self._update_navigation()
        self.refresh_library();self.status.setText(f'Removed {entry.name} from the list. No files were deleted.')

    def open_manager(self,entry):
        self.select_server(entry,7)
        if self.selected_entry is None:return
        self.pending_server_update=None;self.update_install.setEnabled(False);self.update_result.setText('Choose Check for update.')
        self.pending_server_upgrade=None;self.upgrade_install.setEnabled(False);self.upgrade_check.setEnabled(False);self.upgrade_version.clear();self.upgrade_version.setPlaceholderText('Load newer versions');self.upgrade_result.setText('Load the supported versions, then choose where you want to move this server.')
        properties=read_properties(entry.path)
        try:config=json.loads((Path(entry.path)/'easyservers.json').read_text(encoding='utf-8'))
        except (OSError,ValueError):config={}
        def number(key,default,low,high):
            try:return max(low,min(high,int(properties.get(key,default))))
            except (TypeError,ValueError):return default
        bedrock=entry.kind=='Bedrock'
        self.manage_title.setText(entry.name.upper())
        self.manage_note.setText(f'{entry.kind} • Minecraft {entry.version} • Changes apply the next time the server starts.')
        for control in (self.manage_ram,self.manage_java):control.setVisible(not bedrock);self.property_labels[control].setVisible(not bedrock)
        self.prop_pvp.setVisible(not bedrock);self.property_labels[self.prop_motd].setText('Server name' if bedrock else 'Server description');self.property_labels[self.prop_sim].setText('Tick distance' if bedrock else 'Simulation distance')
        self.prop_mode.clear();self.prop_mode.addItems(['survival','creative','adventure']+([] if bedrock else ['spectator']))
        self.prop_view.setRange(5 if bedrock else 2,32);self.prop_sim.setRange(4 if bedrock else 2,12 if bedrock else 32)
        self.manage_ram.setValue(max(1,min(128,int(config.get('ram',4)))));self.manage_java.setText(str(config.get('java','java')))
        self.prop_motd.setText(properties['server-name'] if bedrock else properties['motd']);self.prop_mode.setCurrentText(properties['gamemode']);self.prop_difficulty.setCurrentText(properties['difficulty'])
        self.prop_players.setValue(number('max-players',10 if bedrock else 20,1,1000));self.prop_port.setValue(number('server-port',19132 if bedrock else 25565,1,65535));self.prop_view.setValue(number('view-distance',32 if bedrock else 8,5 if bedrock else 2,32));self.prop_sim.setValue(number('tick-distance' if bedrock else 'simulation-distance',4 if bedrock else 8,4 if bedrock else 2,12 if bedrock else 32))
        self.prop_online.setChecked(properties['online-mode'].lower()=='true');self.prop_whitelist.setChecked(properties['allow-list' if bedrock else 'white-list'].lower()=='true');self.prop_pvp.setChecked(properties['pvp'].lower()=='true');self.refresh_backups()
        self.auto_forward.setChecked(bool(config.get('auto_port_forward',False)))
        self.auto_backup_launch.setChecked(bool(config.get('auto_backup_before_launch',False)));self.auto_backup_keep.setValue(max(1,min(20,int(config.get('auto_backup_keep',5)))))
        self.auto_stop_empty.setChecked(bool(config.get('auto_stop_empty',False)));self.auto_stop_minutes.setValue(max(5,min(240,int(config.get('auto_stop_minutes',30)))))
        self.auto_restart_crash.setChecked(bool(config.get('auto_restart_crash',False)))
        self.run_server_check(silent=True)

    def save_server_properties(self):
        if not self.selected_entry:self.error('Choose a server from My servers first.');return
        if self.process.state()!=QProcess.NotRunning and self.server==Path(self.selected_entry.path):self.error('Stop the server before changing its settings.');return
        if self.auto_forward.isChecked() and not self.prop_online.isChecked():self.error('Direct internet sharing requires verified Minecraft accounts. Turn that setting on, or use Playit from Share.');return
        if self.auto_forward.isChecked() and not self.prop_whitelist.isChecked():self.error('Direct internet sharing requires the player allow-list. Turn it on and add each friend, or use Playit from Share.');return
        bedrock=self.selected_entry.kind=='Bedrock'
        if bedrock:
            changes={'server-name':self.prop_motd.text(),'gamemode':self.prop_mode.currentText(),'difficulty':self.prop_difficulty.currentText(),'max-players':str(self.prop_players.value()),'server-port':str(self.prop_port.value()),'view-distance':str(self.prop_view.value()),'tick-distance':str(self.prop_sim.value()),'online-mode':str(self.prop_online.isChecked()).lower(),'allow-list':str(self.prop_whitelist.isChecked()).lower(),'transport':'nethernet'}
        else:
            changes={'motd':self.prop_motd.text(),'gamemode':self.prop_mode.currentText(),'difficulty':self.prop_difficulty.currentText(),'max-players':str(self.prop_players.value()),'server-port':str(self.prop_port.value()),'view-distance':str(self.prop_view.value()),'simulation-distance':str(self.prop_sim.value()),'online-mode':str(self.prop_online.isChecked()).lower(),'white-list':str(self.prop_whitelist.isChecked()).lower(),'pvp':str(self.prop_pvp.isChecked()).lower()}
        try:
            update_properties(self.selected_entry.path,changes)
            file=Path(self.selected_entry.path)/'easyservers.json';config=json.loads(file.read_text(encoding='utf-8'))
            if not bedrock:config['ram']=self.manage_ram.value();config['java']=self.manage_java.text().strip() or 'java'
            config['auto_port_forward']=self.auto_forward.isChecked()
            temp=file.with_suffix('.tmp');temp.write_text(json.dumps(config,indent=2),encoding='utf-8');os.replace(temp,file)
            server_path=str(Path(self.selected_entry.path).resolve());self.direct_forwarding_approvals={approval for approval in self.direct_forwarding_approvals if approval[0]!=server_path}
            sharing=' Automatic router sharing is on.' if self.auto_forward.isChecked() else ''
            self.status.setText('Server settings saved. They will be used on the next launch.'+sharing)
            self.run_server_check(silent=True)
        except Exception as exc:self.error(str(exc))

    def apply_easy_mode(self):
        if not self.selected_entry:self.error('Choose a server from My servers first.');return
        memory=total_memory_gb();recommendation=recommend_resources(memory,self.selected_entry.kind,self.host_and_play.isChecked())
        if self.selected_entry.kind!='Bedrock':self.manage_ram.setValue(recommendation['ram_gb'])
        self.prop_view.setValue(recommendation['view_distance']);self.prop_sim.setValue(recommendation['simulation_distance'])
        allocation='native Bedrock memory management' if self.selected_entry.kind=='Bedrock' else f"{recommendation['ram_gb']} GB server memory"
        summary=f"Recommended: {allocation}, view distance {recommendation['view_distance']}, simulation distance {recommendation['simulation_distance']}. Profile: {recommendation['profile']}."
        if recommendation['warning']:summary+=' '+recommendation['warning']
        self.hardware_summary.setText(summary);self.status.setText('Easy Mode filled in recommended values. Open Settings to review them, then Save settings.')

    def save_automation(self):
        if not self.selected_entry:self.error('Choose a server from My servers first.');return
        try:
            file=Path(self.selected_entry.path)/'easyservers.json';config=json.loads(file.read_text(encoding='utf-8'))
            values={
                'auto_backup_before_launch':self.auto_backup_launch.isChecked(),
                'auto_backup_keep':self.auto_backup_keep.value(),
                'auto_stop_empty':self.auto_stop_empty.isChecked(),
                'auto_stop_minutes':self.auto_stop_minutes.value(),
                'auto_restart_crash':self.auto_restart_crash.isChecked(),
            }
            config.update(values);temp=file.with_suffix('.tmp');temp.write_text(json.dumps(config,indent=2),encoding='utf-8');os.replace(temp,file)
            if self.running_server and Path(self.selected_entry.path)==self.running_server:self.runtime_config.update(values)
            enabled=[]
            if values['auto_backup_before_launch']:enabled.append('pre-launch backups')
            if values['auto_stop_empty']:enabled.append(f"empty stop after {values['auto_stop_minutes']} minutes")
            if values['auto_restart_crash']:enabled.append('crash recovery')
            self.status.setText('Automation saved'+((' • '+', '.join(enabled)) if enabled else ' • all optional automation is off')+'.')
        except Exception as exc:self.error(str(exc))

    def run_server_check(self,checked=False,silent=False):
        if not self.selected_entry:
            if not silent:self.error('Choose a server from My servers first.')
            return []
        try:
            folder=Path(self.selected_entry.path);config=json.loads((folder/'easyservers.json').read_text(encoding='utf-8'))
            checks=check_server(folder,config);report=format_report(self.selected_entry.name,checks)
            self.last_health_checks=checks;self.doctor_report=report;self.doctor_result.setPlainText(report);self.doctor_copy.setEnabled(True)
            errors=len(blocking_issues(checks));warnings=sum(item.level=='warning' for item in checks)
            if errors:
                self.doctor_result.setStyleSheet('border:1px solid #a84a4a;')
                message=f'Server Doctor found {errors} issue(s) that must be fixed before launch.'
            elif warnings:
                self.doctor_result.setStyleSheet('border:1px solid #b78b45;')
                message=f'Server is launchable • {warnings} recommendation(s) to review.'
            else:
                self.doctor_result.setStyleSheet('border:1px solid #6db55b;')
                message='Server Doctor found no problems.'
            if not silent:self.status.setText(message)
            return checks
        except Exception as exc:
            self.last_health_checks=[];self.doctor_report='Server Doctor could not complete: '+str(exc);self.doctor_result.setPlainText(self.doctor_report);self.doctor_result.setStyleSheet('border:1px solid #a84a4a;');self.doctor_copy.setEnabled(True)
            if not silent:self.error(self.doctor_report)
            return []

    def copy_doctor_report(self):
        if self.doctor_report:
            QApplication.clipboard().setText(self.doctor_report);self.status.setText('Server Doctor report copied. You can paste it into a bug report.')

    def refresh_backups(self):
        self.backup_list.clear()
        if not self.selected_entry:return
        for file in self.backups.list(self.selected_entry):self.backup_list.addItem(file.stem,file)

    def create_backup(self):
        if not self.selected_entry:self.error('Choose a server from My servers first.');return
        if self.process.state()!=QProcess.NotRunning:self.error('Stop the server before creating a backup.');return
        entry=self.selected_entry;self.status.setText('Creating backup…')
        def done(path):self.status.setText(f'Backup created: {Path(path).name}');self.refresh_backups()
        self.job(lambda progress:self.backups.create(entry,progress),done)

    def restore_backup(self):
        if not self.selected_entry or self.backup_list.currentIndex()<0:self.error('Choose a backup to restore.');return
        if self.process.state()!=QProcess.NotRunning:self.error('Stop the server before restoring a backup.');return
        archive=self.backup_list.currentData();answer=QMessageBox.question(self,'Restore this backup?','The selected backup will replace the current server folder. Easy Realms will keep the current folder beside it as a recovery copy.',QMessageBox.Yes|QMessageBox.Cancel,QMessageBox.Cancel)
        if answer!=QMessageBox.Yes:return
        try:
            recovery=self.backups.restore(self.selected_entry,archive);self.status.setText(f'Backup restored. Previous files kept in {recovery.name}.');self.open_manager(self.selected_entry)
        except Exception as exc:self.error(str(exc))

    def check_server_software_update(self):
        if not self.selected_entry:self.error('Choose a server from My servers first.');return
        self.pending_server_update=None;self.update_install.setEnabled(False);self.update_check.setEnabled(False)
        self.update_result.setText('Checking the official server catalog for this Minecraft version…')
        entry=self.selected_entry
        try:config=json.loads((Path(entry.path)/'easyservers.json').read_text(encoding='utf-8'))
        except (OSError,ValueError) as exc:
            self.update_check.setEnabled(True);self.error('Could not read this server’s Easy Realms information: '+str(exc));return
        catalog=Catalog(self.contact.text())
        def done(plan):
            self.update_check.setEnabled(True)
            if not self.selected_entry or self.selected_entry.id!=entry.id:return
            self.pending_server_update=plan if plan.update_available else None
            self.update_install.setEnabled(plan.update_available and self.process.state()==QProcess.NotRunning)
            if plan.update_available:
                tracking='This older or imported server does not have a tracked build yet; reinstalling the current official build will begin safe update tracking.' if not plan.managed_build else 'A newer same-version server build is available.'
                self.update_result.setText(f'{tracking}\n\nInstalled: {plan.installed_build}\nAvailable: {plan.available_build}\nMinecraft: {plan.minecraft_version}')
                self.status.setText('Server software update available. Review it, then choose Back up & install.')
            else:
                self.update_result.setText(f'UP TO DATE\n\n{plan.kind} {plan.minecraft_version} • {plan.available_build}')
                self.status.setText('This server is already on the newest tracked build for its Minecraft version.')
        def failed(message):
            self.update_check.setEnabled(True);self.update_result.setText('Update check unavailable.\n\n'+message);self.error(message)
        self.job(lambda _:check_update(catalog,config),done,failed)

    def install_server_software_update(self):
        if not self.selected_entry or not self.pending_server_update:self.error('Check for a server update first.');return
        if self.process.state()!=QProcess.NotRunning:self.error('Stop the server before installing server software updates.');return
        entry=self.selected_entry;plan=self.pending_server_update
        answer=QMessageBox.question(self,'Back up and install this update?',f'Easy Realms will create a complete backup, then replace only the {plan.kind} server software for Minecraft {plan.minecraft_version}.\n\nInstalled: {plan.installed_build}\nAvailable: {plan.available_build}\n\nWorlds, settings, add-ons and player access files will be preserved.',QMessageBox.Yes|QMessageBox.Cancel,QMessageBox.Cancel)
        if answer!=QMessageBox.Yes:return
        try:config=json.loads((Path(entry.path)/'easyservers.json').read_text(encoding='utf-8'))
        except (OSError,ValueError) as exc:self.error(str(exc));return
        catalog=Catalog(self.contact.text());update_cancel=threading.Event();self.update_check.setEnabled(False);self.update_install.setEnabled(False);self.update_result.setText('Creating a full recovery backup before the update…')
        def work(progress):
            backup=self.backups.create(entry,progress)
            progress(0,'Backup complete. Downloading the server update…')
            result=install_update(catalog,entry.path,config,plan.spec,progress,update_cancel)
            return backup,result
        def done(value):
            backup,_=value;self.pending_server_update=None;self.update_check.setEnabled(True);self.update_install.setEnabled(False);self.refresh_backups()
            self.update_result.setText(f'UPDATE INSTALLED\n\n{plan.kind} {plan.minecraft_version} • {plan.available_build}\nRecovery backup: {Path(backup).name}')
            self.status.setText('Server software updated. Launch it and check the console; the full recovery backup is available under Backups.')
            refreshed=self.library.add(entry.path);self.selected_entry=refreshed;self.refresh_library()
        def failed(message):
            self.update_check.setEnabled(True);self.update_install.setEnabled(self.pending_server_update is not None);self.update_result.setText('UPDATE NOT INSTALLED\n\n'+message+'\n\nAny completed recovery backup remains available under Backups.');self.error(message)
        self.job(work,done,failed)

    def reset_upgrade_plan(self,*_):
        self.pending_server_upgrade=None
        if hasattr(self,'upgrade_install'):self.upgrade_install.setEnabled(False)

    def load_upgrade_versions(self):
        if not self.selected_entry:self.error('Choose a server from My servers first.');return
        entry=self.selected_entry;self.reset_upgrade_plan();self.upgrade_load.setEnabled(False);self.upgrade_check.setEnabled(False);self.upgrade_version.clear();self.upgrade_version.setPlaceholderText('Loading newer versions…');self.upgrade_result.setText('Checking which newer Minecraft releases support this server type…')
        catalog=Catalog(self.contact.text())
        def done(versions):
            self.upgrade_load.setEnabled(True)
            if not self.selected_entry or self.selected_entry.id!=entry.id:return
            self.upgrade_version.addItems(versions);self.upgrade_check.setEnabled(bool(versions));self.upgrade_version.setPlaceholderText('No newer supported versions' if not versions else 'Choose a target version')
            if versions:self.upgrade_result.setText(f'Choose a target newer than Minecraft {entry.version}, then run the compatibility check.')
            else:self.upgrade_result.setText(f'No newer supported {entry.kind} versions are currently available after Minecraft {entry.version}.')
        def failed(message):
            self.upgrade_load.setEnabled(True);self.upgrade_result.setText('Could not load upgrade versions.\n\n'+message);self.error(message)
        self.job(lambda _:upgrade_versions(catalog,entry.kind,entry.version),done,failed)

    def check_server_version_upgrade(self):
        if not self.selected_entry or not self.upgrade_version.currentText():self.error('Load and choose a newer Minecraft version first.');return
        entry=self.selected_entry;target=self.upgrade_version.currentText();self.reset_upgrade_plan();self.upgrade_load.setEnabled(False);self.upgrade_check.setEnabled(False);self.upgrade_result.setText('Checking server software, Java requirements and managed add-ons…')
        try:config=json.loads((Path(entry.path)/'easyservers.json').read_text(encoding='utf-8'))
        except (OSError,ValueError) as exc:
            self.upgrade_load.setEnabled(True);self.upgrade_check.setEnabled(True);self.error(str(exc));return
        catalog=Catalog(self.contact.text())
        def done(plan):
            self.upgrade_load.setEnabled(True);self.upgrade_check.setEnabled(True)
            if not self.selected_entry or self.selected_entry.id!=entry.id:return
            lines=[f'{plan.kind} • Minecraft {plan.current_version} → {plan.target_version}',f'Server build: {plan.available_build}']
            if plan.spec.get('java'):lines.append(f'Requires Java {plan.spec["java"]}; Easy Realms will validate or install it before changing server files.')
            if plan.addon_summary:lines.append('Compatible managed add-ons: '+', '.join(plan.addon_summary))
            if plan.warnings:lines.extend('Warning: '+item for item in plan.warnings)
            if plan.blockers:
                lines.extend('BLOCKED: '+item for item in plan.blockers);lines.append('Resolve every blocker before upgrading.')
                self.status.setText(f'Upgrade blocked by {len(plan.blockers)} compatibility issue(s).')
            else:
                self.pending_server_upgrade=plan;self.upgrade_install.setEnabled(self.process.state()==QProcess.NotRunning);lines.append('READY: A complete backup will be created before anything changes.')
                self.status.setText('Version upgrade passed its preflight checks. Review the warning before continuing.')
            self.upgrade_result.setText('\n'.join(lines))
        def failed(message):
            self.upgrade_load.setEnabled(True);self.upgrade_check.setEnabled(True);self.upgrade_result.setText('Upgrade check failed.\n\n'+message);self.error(message)
        self.job(lambda _:check_upgrade(catalog,entry.path,config,target),done,failed)

    def install_server_version_upgrade(self):
        if not self.selected_entry or not self.pending_server_upgrade:self.error('Run the version compatibility check first.');return
        if self.process.state()!=QProcess.NotRunning:self.error('Stop the server before upgrading its Minecraft version.');return
        entry=self.selected_entry;plan=self.pending_server_upgrade
        answer=QMessageBox.warning(self,'Upgrade this Minecraft world?',f'This will move {entry.name} from Minecraft {plan.current_version} to {plan.target_version}.\n\nA full recovery backup will be created first. Once the upgraded world has been opened, do not try to use it with the older Minecraft version.\n\nContinue with the backup and upgrade?',QMessageBox.Yes|QMessageBox.Cancel,QMessageBox.Cancel)
        if answer!=QMessageBox.Yes:return
        try:config=json.loads((Path(entry.path)/'easyservers.json').read_text(encoding='utf-8'))
        except (OSError,ValueError) as exc:self.error(str(exc));return
        catalog=Catalog(self.contact.text());upgrade_cancel=threading.Event();self.upgrade_load.setEnabled(False);self.upgrade_check.setEnabled(False);self.upgrade_install.setEnabled(False);self.upgrade_result.setText('Creating the mandatory recovery backup…')
        def work(progress):
            backup=self.backups.create(entry,progress)
            try:
                if plan.kind!='Bedrock':
                    chosen=str(config.get('java','Automatic'));automatic_root=(self.data/'java').resolve()
                    try:
                        if Path(chosen).expanduser().resolve().is_relative_to(automatic_root):chosen='Automatic'
                    except (OSError,ValueError):pass
                    config['java']=ensure_java(int(plan.spec['java']),chosen,progress,upgrade_cancel,java_major)
                install_update(catalog,entry.path,config,plan.spec,progress,upgrade_cancel,allow_version_change=True)
                if plan.addon_roots:
                    progress(92,'Installing compatible add-on versions…')
                    AddonManager(entry.path,plan.kind,plan.target_version).install_many(list(plan.addon_roots))
                return backup
            except Exception as exc:
                try:self.backups.restore(entry,backup)
                except Exception as restore_exc:raise ValueError(f'Upgrade failed and automatic recovery also failed: {restore_exc}. Do not launch this server; restore {Path(backup).name} manually.') from exc
                raise ValueError(f'Upgrade failed, so Easy Realms automatically restored the previous server: {exc}') from exc
        def done(backup):
            refreshed=self.library.add(entry.path);self.selected_entry=refreshed;self.server=Path(refreshed.path);self.pending_server_upgrade=None;self.upgrade_load.setEnabled(True);self.upgrade_check.setEnabled(False);self.upgrade_install.setEnabled(False);self.upgrade_version.clear();self.refresh_backups();self.refresh_library();self.manage_note.setText(f'{refreshed.kind} • Minecraft {refreshed.version} • Upgrade complete; launch and review the console.')
            self.upgrade_result.setText(f'UPGRADE INSTALLED\n\nMinecraft {plan.current_version} → {plan.target_version}\nRecovery backup: {Path(backup).name}\n\nLaunch the server and review its console before inviting players.')
            self.status.setText('Minecraft version upgraded. The recovery backup remains available under Backups.');self.run_server_check(silent=True)
        def failed(message):
            self.upgrade_load.setEnabled(True);self.upgrade_check.setEnabled(True);self.pending_server_upgrade=None;self.upgrade_install.setEnabled(False);self.upgrade_result.setText('UPGRADE NOT INSTALLED\n\n'+message);self.refresh_backups();self.error(message)
        self.job(work,done,failed)

    def _clear_dynamic_rows(self,layout):
        while layout.count()>1:
            item=layout.takeAt(0)
            if item.widget():item.widget().deleteLater()
            elif item.layout():
                while item.layout().count():
                    child=item.layout().takeAt(0)
                    if child.widget():child.widget().deleteLater()

    def _addon_manager(self):
        if not self.selected_entry:raise ValueError('Choose a Fabric or Paper server from My servers first.')
        if self.selected_entry.kind not in ('Fabric','Paper'):raise ValueError('Mods and plugins are available for Fabric and Paper servers.')
        return AddonManager(self.selected_entry.path,self.selected_entry.kind,self.selected_entry.version)

    def _addon_empty(self,layout,text):
        label=QLabel(text);label.setObjectName('muted');label.setWordWrap(True);layout.insertWidget(0,label)

    def refresh_addons_page(self):
        self._clear_dynamic_rows(self.addon_installed)
        try:
            manager=self._addon_manager();entry=self.selected_entry
        except Exception as exc:
            self.addon_context.setText(str(exc));self.preset_frame.setVisible(False);self.addon_search.setEnabled(False);self.addon_search_button.setEnabled(False);self._addon_empty(self.addon_installed,'No compatible server selected.');return
        self.addon_context.setText(f'{entry.name} • {entry.kind} • Minecraft {entry.version} • Files go into {manager.folder.name}/')
        self.preset_frame.setVisible(entry.kind=='Fabric');self.addon_search.setEnabled(True);self.addon_search_button.setEnabled(True)
        context=(entry.id,entry.kind,entry.version)
        if context!=self.addon_context_key:
            self.addon_context_key=context;self._clear_dynamic_rows(self.addon_results);self._addon_empty(self.addon_results,'Search for a mod or plugin to begin.')
        try:installed=manager.installed()
        except Exception as exc:self._addon_empty(self.addon_installed,str(exc));return
        if not installed:self._addon_empty(self.addon_installed,'Nothing installed through Easy Realms yet.')
        for item in installed:
            card=QFrame();card.setObjectName('serverCard');row=QHBoxLayout(card);row.setContentsMargins(12,10,12,10)
            copy=QVBoxLayout();name=QLabel(str(item.get('name','Unknown add-on')));name.setObjectName('smallHeading');copy.addWidget(name)
            dependency=bool(item.get('installed_as_dependency'));details=f"{item.get('version_number','?')} • {item.get('file','')}"
            if dependency:details+=' • Required dependency (managed automatically)'
            requirement=item.get('client_requirement','not required')
            if requirement!='not required':details+=f' • Client: {requirement}'
            desc=QLabel(details);desc.setObjectName('muted');desc.setWordWrap(True);copy.addWidget(desc);row.addLayout(copy,1)
            if not dependency:
                update=TextureButton('Check update');update.clicked.connect(lambda checked=False,p=item['project_id'],n=item.get('name',item['project_id']),v=item.get('version_id'):self.preview_addon_install([p],n,v));row.addWidget(update)
                remove=TextureButton('Remove');remove.clicked.connect(lambda checked=False,p=item['project_id'],n=item.get('name',item['project_id']):self.remove_addon(p,n));row.addWidget(remove)
            self.addon_installed.insertWidget(self.addon_installed.count()-1,card)

    def search_addons(self):
        try:manager=self._addon_manager()
        except Exception as exc:self.error(str(exc));return
        query=self.addon_search.text().strip()
        if not query:self.error('Enter something to search for on Modrinth.');return
        self.addon_search_button.setEnabled(False);self.status.setText(f'Searching Modrinth for {manager.loader.title()} add-ons…')
        def done(results):
            self.addon_search_button.setEnabled(True);self._clear_dynamic_rows(self.addon_results)
            if not results:self._addon_empty(self.addon_results,'No server-compatible results matched this exact Minecraft version and loader.')
            for hit in results:
                project_id=str(hit.get('project_id') or hit.get('slug'))
                card=QFrame();card.setObjectName('serverCard');row=QHBoxLayout(card);row.setContentsMargins(12,10,12,10)
                copy=QVBoxLayout();title=QLabel(str(hit.get('title') or hit.get('slug') or project_id));title.setObjectName('smallHeading');copy.addWidget(title)
                description=QLabel(str(hit.get('description') or 'No description provided.'));description.setObjectName('muted');description.setWordWrap(True);copy.addWidget(description)
                author=hit.get('author','Unknown creator');downloads=int(hit.get('downloads',0) or 0);meta=QLabel(f'By {author} • {downloads:,} downloads');meta.setObjectName('muted');copy.addWidget(meta);row.addLayout(copy,1)
                install=TextureButton('Install');install.clicked.connect(lambda checked=False,p=project_id,n=hit.get('title',project_id):self.preview_addon_install([p],str(n)));row.addWidget(install)
                self.addon_results.insertWidget(self.addon_results.count()-1,card)
            self.status.setText(f'Found {len(results)} compatible Modrinth result(s).')
        def failed(message):self.addon_search_button.setEnabled(True);self.error(message)
        self.job(lambda _:manager.search(query),done,failed)

    def preview_addon_install(self,projects,label,current_version_id=None):
        try:manager=self._addon_manager()
        except Exception as exc:self.error(str(exc));return
        if self.process.state()!=QProcess.NotRunning:
            self.error('Stop the server before installing or updating mods and plugins.');return
        self.status.setText(f'Checking {label} and its required dependencies…')
        def done(preview):
            roots=[item for item in preview if not item['is_dependency']]
            if current_version_id and len(roots)==1 and roots[0]['version_id']==current_version_id:
                self.status.setText(f'{label} is already on the newest compatible version.');QMessageBox.information(self,'Already up to date',f'{label} is already on the newest compatible version for Minecraft {manager.minecraft_version}.');return
            required=[item['name'] for item in preview if item['client_requirement']=='required']
            recommended=[item['name'] for item in preview if item['client_requirement']=='recommended']
            unknown=[item['name'] for item in preview if item['client_requirement']=='unknown']
            dependencies=[item['name'] for item in preview if item['is_dependency']]
            lines=[f"Install {', '.join(item['name']+' '+str(item['version_number']) for item in roots)}?",f'Minecraft {manager.minecraft_version} • {manager.loader.title()}']
            if dependencies:lines.append('Required dependencies included: '+', '.join(dependencies))
            if required:lines.append('EVERY PLAYER MUST INSTALL MATCHING VERSIONS: '+', '.join(required))
            if recommended:lines.append('Recommended on player clients: '+', '.join(recommended))
            if unknown:lines.append('Client requirement is not declared; check the project page: '+', '.join(unknown))
            if any(item['project_id']=='simple-voice-chat' for item in preview):
                lines.append('VOICE NETWORKING REQUIRED: After the first launch, create a playit “MC: Simple Voice Chat” tunnel to 127.0.0.1:24454, then put its public address and port in config/voicechat/voicechat-server.properties as voice_host=ADDRESS:PORT.')
            answer=QMessageBox.question(self,'Confirm Modrinth install','\n\n'.join(lines),QMessageBox.Yes|QMessageBox.Cancel,QMessageBox.Cancel)
            if answer==QMessageBox.Yes:self._install_addons(manager,projects,label)
            else:self.status.setText('Install cancelled. No files were changed.')
        self.job(lambda _:manager.preview_many(projects),done)

    def _install_addons(self,manager,projects,label):
        self.status.setText(f'Downloading and verifying {label} from Modrinth…')
        def done(installed):
            names=', '.join(item['name'] for item in installed);self.status.setText('Installed: '+names);self.refresh_addons_page()
        self.job(lambda _:manager.install_many(projects),done)

    def remove_addon(self,project_id,name):
        try:manager=self._addon_manager()
        except Exception as exc:self.error(str(exc));return
        if self.process.state()!=QProcess.NotRunning:self.error('Stop the server before removing mods and plugins.');return
        answer=QMessageBox.question(self,'Remove this add-on?',f'Remove {name}? Required dependencies that nothing else uses will also be removed. Config files and world data will be kept.',QMessageBox.Yes|QMessageBox.Cancel,QMessageBox.Cancel)
        if answer!=QMessageBox.Yes:return
        try:
            removed=manager.remove(project_id);self.status.setText('Removed: '+', '.join(removed));self.refresh_addons_page()
        except Exception as exc:self.error(str(exc))

    def confirm_direct_forwarding(self,config,properties,requests):
        server_key=str(Path(self.server).resolve())
        if str(properties.get('online-mode','true')).lower()!='true':
            QMessageBox.critical(self,'Direct sharing blocked','Verified Minecraft accounts are disabled. Easy Realms will not expose this server directly to the internet. Turn online-mode on, or use Playit from the Share tab.');return False
        allow_key='allow-list' if config.get('kind')=='Bedrock' else 'white-list'
        if str(properties.get(allow_key,'false')).lower()!='true':
            QMessageBox.critical(self,'Direct sharing blocked','The player allow-list is disabled. Easy Realms will not expose this server directly to the internet until the allow-list is on and your friends are added. Turn it on in Manage → Settings, or use Playit from Share.');return False
        port_key=tuple(sorted((item.protocol,item.port) for item in requests));approval_key=(server_key,port_key)
        if approval_key in self.direct_forwarding_approvals:return True
        ports=', '.join(f'{item.protocol} {item.port}' for item in requests)
        box=QMessageBox(self);box.setIcon(QMessageBox.Warning);box.setWindowTitle('Expose this port directly?')
        box.setText(f'Direct UPnP will expose {ports} through your router and may reveal your home IP to players. The temporary rule lasts ten minutes and is renewed only while this server runs.\n\nVerified accounts and the allow-list are currently enabled, but Playit is still safer because it hides your home IP and does not change the router.')
        playit_button=box.addButton('Use Playit instead',QMessageBox.AcceptRole)
        open_button=box.addButton('Open temporarily this session',QMessageBox.DestructiveRole)
        box.addButton(QMessageBox.Cancel);box.setDefaultButton(playit_button);box.exec()
        if box.clickedButton()==playit_button:
            self.navigate(5);return False
        if box.clickedButton()!=open_button:return False
        self.direct_forwarding_approvals.add(approval_key);return True

    def start(self,checked=False,skip_backup=False):
        try:
            if not self.server:raise ValueError('Choose a server from My servers first.')
            config=json.loads((self.server/'easyservers.json').read_text(encoding='utf-8'))
            self.last_health_checks=check_server(self.server,config)
            issues=blocking_issues(self.last_health_checks)
            if issues:
                name=str(config.get('name',self.server.name));self.doctor_report=format_report(name,self.last_health_checks)
                self.console.clear();self.console.appendPlainText(self.doctor_report);self.status.setText(f'Server Doctor blocked launch: {len(issues)} issue(s) need fixing.')
                QMessageBox.critical(self,'Server is not ready','Server Doctor found a problem that would prevent a safe launch. Open Manage → Server Doctor for the exact fix.')
                return
            if config.get('auto_backup_before_launch') and not skip_backup:
                if self.auto_backup_in_progress:return
                if not self.selected_entry or Path(self.selected_entry.path)!=Path(self.server):raise ValueError('Select this server again before creating its automatic backup.')
                entry=self.selected_entry;keep=max(1,min(20,int(config.get('auto_backup_keep',5))))
                self.auto_backup_in_progress=True;self.launch.setEnabled(False);self.status.setText('Creating the automatic pre-launch backup…')
                def backed_up(path):
                    self.auto_backup_in_progress=False
                    try:self.backups.prune(entry,keep,automatic_only=True)
                    except Exception as exc:self.console.appendPlainText('[Easy Realms] Backup retention warning: '+str(exc))
                    self.status.setText(f'Backup ready: {Path(path).name}');self.refresh_backups();self.start(skip_backup=True)
                def backup_failed(message):
                    self.auto_backup_in_progress=False;self.launch.setEnabled(True);self.error('Automatic backup failed; the server was not started. '+message)
                self.job(lambda progress:self.backups.create(entry,progress,automatic=True),backed_up,backup_failed);return
            self.server_started=False;self.stop_requested=False
            if config.get('auto_port_forward') and not self.active_port_mappings:
                properties=read_properties(self.server);requests=mapping_requests(config.get('kind','Vanilla'),properties)
                if not self.confirm_direct_forwarding(config,properties,requests):self.launch.setEnabled(True);return
                self.launch.setEnabled(False);self.status.setText('Finding your router and opening the Minecraft port…')
                description='Easy Realms - '+str(config.get('name',self.server.name))
                def opened(mappings):
                    self.active_port_mappings=list(mappings);self.mapping_server=Path(self.server);self.forwarding_timer.start()
                    self._launch_process(config)
                def unavailable(message):
                    QMessageBox.warning(self,'Could not open the router port',message+'\n\nThe server will still start for this PC and your local network. You can use playit.gg or set up the port manually.')
                    self._launch_process(config)
                    self.console.appendPlainText('[Easy Realms] Automatic router sharing unavailable: '+message)
                self.job(lambda _:PortForwarder().open(requests,description),opened,unavailable);return
            self._launch_process(config)
        except Exception as exc:self.error(str(exc))

    def _launch_process(self,config):
        target=Path(self.server)
        if self.running_server!=target:self.crash_times=[]
        self.running_server=target;self.runtime_config=dict(config);self.empty_since=None;self.last_player_count=None;self.server_started_at=None;self.recovery_pending=False;self.console_tail=''
        self.process.setWorkingDirectory(str(self.server));self.console.clear()
        for item in self.last_health_checks:
            if item.level=='warning':self.console.appendPlainText(f'[Server Doctor] {item.title}: {item.detail}')
        if self.active_port_mappings:
            labels=', '.join(f'{item.protocol} {item.port}' for item in self.active_port_mappings)
            self.console.appendPlainText(f'[Easy Realms] Direct router sharing active: {labels}. This can expose your home IP; Playit is the safer option.')
            address=self._friend_address()
            if address:self.console.appendPlainText(f'[Easy Realms] Friend address: {address}')
            elif self.active_port_mappings[0].external_ip:self.console.appendPlainText('[Easy Realms] Your router reported a non-public internet address. Your ISP may use carrier NAT; use playit.gg if friends cannot connect.')
        if config.get('kind')=='Bedrock':
            self.process.start(str(self.server/config.get('executable','bedrock_server.exe')),[])
            message='Starting Bedrock server… Windows may ask for private-network firewall access.'
        else:
            self.process.start(config['java'],['-Xms1G',f"-Xmx{int(config['ram'])}G",'-jar',config.get('jar','server.jar'),'nogui'])
            message='Starting server… first launch may download dependencies.'
        self.launch.setEnabled(False);self.restart.setEnabled(False);self.stop.setEnabled(True);self.status.setText(message)

    def performance_started(self):
        process_id=int(self.process.processId())
        if process_id:
            try:self.process_monitor.reset(process_id)
            except OSError:self.process_monitor.reset()
        self.update_performance()

    def update_performance(self):
        if self.process.state()!=QProcess.Running:
            return
        sample=self.process_monitor.sample()
        if sample is None:
            self.performance_note.setText('Live process details are temporarily unavailable.')
            return
        memory_limit=None if self.runtime_config.get('kind')=='Bedrock' else int(self.runtime_config.get('ram',0) or 0)
        self.performance_values['cpu'].setText(f'{sample.cpu_percent:.0f}%')
        self.performance_values['memory'].setText(format_memory(sample.memory_bytes))
        self.performance_values['uptime'].setText(format_uptime(sample.uptime_seconds))
        self.performance_values['players'].setText('—' if self.last_player_count is None else str(self.last_player_count))
        self.performance_note.setText(load_message(sample.cpu_percent,sample.memory_bytes,memory_limit))

    def reset_performance(self):
        self.process_monitor.reset()
        for value in self.performance_values.values():value.setText('—')
        self.performance_note.setText('Start the server to see live performance.')

    def command_state(self,state):
        running=state==QProcess.Running
        stopped=state==QProcess.NotRunning
        self.command_input.setEnabled(running);self.send.setEnabled(running);self.restart.setEnabled(running and not self.restart_pending)
        if hasattr(self,'update_install'):self.update_install.setEnabled(stopped and self.pending_server_update is not None)
        if hasattr(self,'upgrade_install'):self.upgrade_install.setEnabled(stopped and self.pending_server_upgrade is not None)
        self._update_navigation()
        if self.pages.currentIndex()==6:self.refresh_library()
        if hasattr(self,'player_action_buttons') and self.pages.currentIndex()==9:self.refresh_players_page()

    def _write_server_command(self,command):
        if self.process.state()!=QProcess.Running:
            self.error('Start the server before sending commands.');return False
        if not command or any(character in command for character in ('\n','\r','\x00')):
            self.error('Easy Realms refused an invalid multi-line command.');return False
        data=(command+'\n').encode('utf-8')
        if self.process.write(data)!=len(data):
            self.error('Could not queue the command. Check the server console.');return False
        self.console.appendPlainText('> '+command)
        return True

    def send_command(self):
        command=self.command_input.text().strip()
        if command.startswith('/'):command=command[1:].lstrip()
        if not command:return
        if not self._write_server_command(command):return
        self.command_input.remember(command);self.command_input.setFocus()

    def process_error(self, error):
        log_warning('Server process error: %s',self.process.errorString())
        self.error(self.process.errorString())
        if self.process.state()==QProcess.NotRunning:
            self.restart_pending=False;self.launch.setEnabled(self.server is not None);self.restart.setEnabled(False);self.stop.setEnabled(False)
            if self.active_port_mappings:self._remove_port_mappings('Server could not start.')
    def read_console(self):
        text=bytes(self.process.readAllStandardOutput()).decode('utf-8',errors='replace');self.console.appendPlainText(text.rstrip())
        combined=self.console_tail+text;players=parse_player_count(combined)
        if players is not None:
            self.console_tail='';self.last_player_count=players
            self.performance_values['players'].setText(str(players))
            if players>0:self.empty_since=None
            elif self.empty_since is None:self.empty_since=time.monotonic()
            if players==0 and self.runtime_config.get('auto_stop_empty') and self.empty_since is not None and not self.stop_requested:
                minutes=max(5,min(240,int(self.runtime_config.get('auto_stop_minutes',30))))
                if time.monotonic()-self.empty_since>=minutes*60:
                    self.console.appendPlainText(f'[Easy Realms] Nobody has been online for {minutes} minutes. Saving and stopping automatically.')
                    self.stop_server();return
        else:
            last_break=max(combined.rfind('\n'),combined.rfind('\r'))
            self.console_tail=(combined[last_break+1:] if last_break>=0 else combined)[-500:]
        if 'Done (' in text or 'Server started' in text:
            self.server_started=True;self.server_started_at=time.monotonic()
            address=self._friend_address()
            self.status.setText(('Server is running • Friends can try '+address) if address else 'Server is running • Join localhost on this PC')
            self._update_selection_banner()
            if self.pages.currentIndex()==6:self.refresh_library()
            if self.pages.currentIndex()==9:self.refresh_players_page()

    def poll_automation(self):
        if self.process.state()!=QProcess.Running or not self.server_started or self.stop_requested:return
        if self.process.write(b'list\n')<0:self.console.appendPlainText('[Easy Realms] Could not request the current player count.')

    def _friend_address(self):
        if not self.active_port_mappings:return ''
        mapping=self.active_port_mappings[0]
        try:public=ipaddress.ip_address(mapping.external_ip).is_global
        except ValueError:public=False
        return f'{mapping.external_ip}:{mapping.port}' if public else ''
    def restart_server(self):
        if self.process.state()!=QProcess.Running:
            self.error('Wait until the server has fully started before restarting it.');return
        self.restart_pending=True;self.stop_requested=True;self.process.write(b'stop\n');self.status.setText('Saving the world before restart…');self.restart.setEnabled(False);self.stop.setEnabled(False)

    def _resume_running_server(self):
        if not self.running_server:return
        self.server=Path(self.running_server);self.recovery_pending=False;self.start(skip_backup=True)
    def stop_server(self):
        self.restart_pending=False;self.stop_requested=True;self.process.write(b'stop\n');self.status.setText('Stopping server and saving world…');self.restart.setEnabled(False);self.stop.setEnabled(False)
    def stopped(self,exit_code=0,exit_status=None):
        restarting=self.restart_pending;requested=self.stop_requested;started=self.server_started
        crashed=exit_code!=0 or exit_status==QProcess.CrashExit
        if crashed:log_warning('Server process stopped unexpectedly with exit code %s',exit_code)
        self.restart_pending=False;self.stop_requested=False;self.server_started=False;self.restart.setEnabled(False);self.stop.setEnabled(False)
        self.reset_performance()
        self._update_navigation()
        if self.pages.currentIndex()==6:self.refresh_library()
        if self.pages.currentIndex()==9:self.refresh_players_page()
        if restarting and self.server:
            self.recovery_pending=True;self.launch.setEnabled(False);self.status.setText('World saved. Restarting server…');self._update_navigation();QTimer.singleShot(600,self._resume_running_server)
        else:
            self.launch.setEnabled(self.server is not None)
            unexpected=not requested and (crashed or not started)
            if unexpected:
                self.console.appendPlainText(f'[Easy Realms] Server stopped unexpectedly (exit code {exit_code}). Run Server Doctor and copy its report if you need help.')
                prefix='Server stopped unexpectedly.'
            else:prefix='Server stopped.'
            if unexpected and self.runtime_config.get('auto_restart_crash') and self.running_server:
                now=time.monotonic()
                if self.server_started_at and now-self.server_started_at>=600:self.crash_times=[]
                allowed,self.crash_times=restart_decision(self.crash_times,now)
                if allowed:
                    attempt=len(self.crash_times);self.server=Path(self.running_server);self.recovery_pending=True;self.launch.setEnabled(False)
                    self.console.appendPlainText(f'[Easy Realms] Crash recovery attempt {attempt}/3 will start in three seconds.')
                    self.status.setText(f'Server crashed • recovery attempt {attempt}/3…');self._update_navigation();QTimer.singleShot(3000,self._resume_running_server);return
                self.console.appendPlainText('[Easy Realms] Crash recovery stopped after three attempts in ten minutes. Run Server Doctor before launching again.')
                prefix='Crash recovery limit reached.'
            if self.active_port_mappings:self._remove_port_mappings(prefix)
            else:self.status.setText(prefix+' See console for details.')
            self.running_server=None;self.runtime_config={};self.empty_since=None;self.last_player_count=None;self.server_started_at=None;self.recovery_pending=False

    def renew_port_mappings(self):
        if not self.active_port_mappings or self.process.state()!=QProcess.Running or self.jobs:return
        mappings=list(self.active_port_mappings);description='Easy Realms - '+str(self.runtime_config.get('name','Minecraft server'))
        def renewed(_):
            self.console.appendPlainText('[Easy Realms] Temporary router lease renewed for ten minutes.')
        def failed(message):
            self.forwarding_timer.stop();self.console.appendPlainText('[Easy Realms] Router lease renewal stopped: '+message+' The existing temporary rule will expire automatically; switch to Playit for reliable sharing.')
        self.job(lambda _:PortForwarder().renew(mappings,description),renewed,failed)

    def _remove_port_mappings(self,prefix):
        self.forwarding_timer.stop()
        mappings=list(self.active_port_mappings)
        self.active_port_mappings=[];self.mapping_server=None
        if not mappings:self.status.setText(prefix);return
        self.status.setText(prefix+' Closing the router port…')
        def removed(_):
            self.console.appendPlainText('[Easy Realms] Router sharing closed.')
            self.status.setText(prefix+' Router port closed.')
        def failed(message):
            self.console.appendPlainText('[Easy Realms] Could not confirm router cleanup: '+message)
            self.status.setText(prefix+' The router did not confirm cleanup; its temporary mapping should expire automatically.')
        self.job(lambda _:PortForwarder().close(mappings),removed,failed)
    def closeEvent(self,event):
        if self.creating or self.jobs:
            self.error('Wait for the current operation to finish; Cancel stops an active download.');event.ignore();return
        if self.process.state()!=QProcess.NotRunning:
            self.stop_server();self.error('Saving the world. Close the window once the server has stopped.');event.ignore();return
        if self.playit_process.state()!=QProcess.NotRunning:self.cancel_playit_setup()
        event.accept()

if __name__=='__main__':
    if sys.platform=='win32':
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('EasyRealms.Desktop')
    app=QApplication(sys.argv)
    if DIAGNOSTICS is not None:DIAGNOSTICS.install_qt_handler(qInstallMessageHandler)
    app.setWindowIcon(QIcon(str(ASSETS/'app-icon.ico')))
    app.setStyle('Fusion')
    QFontDatabase.addApplicationFont(str(ASSETS/'MinecraftTen-VGORe.ttf'))
    QFontDatabase.addApplicationFont(str(ASSETS/'Minecraft-Seven_v2.ttf'))
    window=Window(offline='--preview' in sys.argv);window.show()
    window.showNormal();window.raise_();window.activateWindow()
    if not window.ensure_agreement():
        window.close();sys.exit(0)
    window.begin_startup()
    ready_file=os.environ.get('EASY_SERVERS_READY_FILE')
    if ready_file:
        QTimer.singleShot(250,lambda:Path(ready_file).write_text('ready',encoding='utf-8') if window.isVisible() else None)
    if '--screenshot' in sys.argv:
        QTimer.singleShot(1800,lambda:(window.grab().save(str(ROOT/'preview.png')),app.quit()))
    exit_code=app.exec()
    finish_diagnostics(exit_code)
    sys.exit(exit_code)
