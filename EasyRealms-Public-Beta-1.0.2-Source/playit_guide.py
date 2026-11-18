"""Interactive Playit setup and safe sharing guidance."""

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from playit_manager import (
    PLAYIT_DASHBOARD_URL,
    PLAYIT_DOWNLOAD_URL,
    PlayitStatus,
    TunnelTarget,
)


class PlayitGuide(QScrollArea):
    setup_requested = Signal()
    setup_cancelled = Signal()
    status_requested = Signal()

    def __init__(self, button_class=QPushButton):
        super().__init__()
        self.button_class = button_class
        self.setWidgetResizable(True)
        self.setFrameShape(QScrollArea.NoFrame)

        content = QWidget()
        self.layout = QVBoxLayout(content)
        self.layout.setContentsMargins(28, 24, 28, 24)
        self.layout.setSpacing(16)

        self._text("PLAY WITH FRIENDS", heading=True)
        self._text("RECOMMENDED: PLAYIT TUNNEL", heading=True)
        self._text(
            "Playit gives friends a public Playit address while keeping your home IP private. "
            "It does not require a router port-forwarding rule, and only the host runs the agent."
        )

        self._build_connection_panel()
        self._build_target_panel()
        self._build_safety_panel()
        self._build_manual_steps()
        self._build_joining_steps()

        source = QLabel(
            'Official links: <a href="https://playit.gg/download/windows" style="color:#9bdd84">'
            'Windows download</a> · <a href="https://playit.gg/support/" style="color:#9bdd84">'
            'support</a> · <a href="https://github.com/playit-cloud/playit-agent" '
            'style="color:#9bdd84">agent source</a><br>Reviewed 13 November 2026.'
        )
        source.setWordWrap(True)
        source.setOpenExternalLinks(True)
        self.layout.addWidget(source)
        self.layout.addStretch()
        self.setWidget(content)

    def _text(self, value, heading=False, muted=False):
        label = QLabel(value)
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        if heading:
            label.setStyleSheet("font-size:20px;color:#9bdd84;")
        elif muted:
            label.setObjectName("muted")
        self.layout.addWidget(label)
        return label

    def _button(self, text, callback):
        button = self.button_class(text)
        button.setMinimumHeight(44)
        button.clicked.connect(callback)
        return button

    @staticmethod
    def _open(url):
        QDesktopServices.openUrl(QUrl(url))

    def _build_connection_panel(self):
        panel = QFrame()
        panel.setObjectName("serverCard")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        title = QLabel("PLAYIT AGENT")
        title.setStyleSheet("font-size:16px;font-weight:bold;")
        layout.addWidget(title)
        self.agent_status = QLabel("Checking whether Playit is installed…")
        self.agent_status.setWordWrap(True)
        layout.addWidget(self.agent_status)
        self.setup_status = QLabel(
            "Playit's installed command opens its own one-time approval page. Passwords, claim links and agent secrets never enter Easy Realms."
        )
        self.setup_status.setObjectName("muted")
        self.setup_status.setWordWrap(True)
        layout.addWidget(self.setup_status)

        actions = QHBoxLayout()
        self.connect_button = self._button("CONNECT PLAYIT", lambda: self.setup_requested.emit())
        self.connect_button.setObjectName("primary")
        self.connect_button.setEnabled(False)
        actions.addWidget(self.connect_button)
        self.check_button = self._button("Check status", lambda: self.status_requested.emit())
        actions.addWidget(self.check_button)
        self.cancel_button = self._button("Cancel setup", lambda: self.setup_cancelled.emit())
        self.cancel_button.setVisible(False)
        actions.addWidget(self.cancel_button)
        actions.addStretch()
        layout.addLayout(actions)

        links = QHBoxLayout()
        links.addWidget(self._button("Download Playit ↗", lambda: self._open(PLAYIT_DOWNLOAD_URL)))
        links.addWidget(self._button("Open tunnel dashboard ↗", lambda: self._open(PLAYIT_DASHBOARD_URL)))
        links.addStretch()
        layout.addLayout(links)
        self.layout.addWidget(panel)

    def _build_target_panel(self):
        panel = QFrame()
        panel.setObjectName("serverCard")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)
        title = QLabel("SELECTED SERVER TARGET")
        title.setStyleSheet("font-size:16px;font-weight:bold;")
        layout.addWidget(title)
        self.target_summary = QLabel("Choose a server from My servers to fill in its safe local target.")
        self.target_summary.setWordWrap(True)
        layout.addWidget(self.target_summary)
        self.target_rows = QVBoxLayout()
        layout.addLayout(self.target_rows)
        self.target_note = QLabel("")
        self.target_note.setObjectName("muted")
        self.target_note.setWordWrap(True)
        layout.addWidget(self.target_note)
        self.layout.addWidget(panel)

    def _build_safety_panel(self):
        self._text("WHY THIS IS THE SAFE DEFAULT", heading=True)
        for line in (
            "• Your router stays untouched and your public home IP is not the join address.",
            "• Easy Realms runs only the Playit command installed in Windows Program Files—not a similarly named file in Downloads or another user-writable folder.",
            "• Playit itself opens the approval page; Easy Realms never opens, reads, copies or stores the claim link or agent secret.",
            "• The tunnel target is always 127.0.0.1, so Playit forwards only to this PC.",
            "• Keep verified accounts and the Minecraft allow-list enabled. Only invite people you trust.",
        ):
            self._text(line)

    def _build_manual_steps(self):
        self._text("FINISH THE TUNNEL", heading=True)
        self._text(
            "HOST SETUP\n"
            "1. Install Playit using the official Windows installer. Return here and choose Check status.\n"
            "2. Choose Connect Playit. The installed Playit app opens its one-time approval page; check that the browser address begins https://playit.gg/claim/ before approving. Never send that claim link to anyone.\n"
            "3. Open the tunnel dashboard, add a tunnel, and copy the selected server values shown above.\n"
            "4. Share the Playit hostname and public port—not 127.0.0.1, the claim link or your home IP.\n"
            "5. Keep the Minecraft server and Playit service running while friends are connected."
        )
        self._text(
            "Simple Voice Chat needs its own UDP tunnel to 127.0.0.1:24454. Every player using voice also needs the mod on their client.",
            muted=True,
        )

    def _build_joining_steps(self):
        self._text("WHAT YOUR FRIENDS DO", heading=True)
        self._text(
            "Friends do not install Easy Realms or Playit. Give them only the public Playit hostname and public port shown in your Playit dashboard.\n\n"
            "JAVA EDITION\n"
            "Open Multiplayer → Add Server, paste the public Playit address, then join. If Playit gives a separate port, use hostname:port.\n\n"
            "BEDROCK EDITION\n"
            "Open Play → Servers → Add Server, enter the public Playit hostname and public port, then join. Console editions may need their own supported custom-server method.\n\n"
            "Never give friends 127.0.0.1, your home IP, a Playit claim link, account password or agent secret."
        )

    def set_agent_status(self, status: PlayitStatus):
        self.agent_status.setText(status.message)
        self.connect_button.setEnabled(status.installed and not status.running)
        self.connect_button.setText("PLAYIT CONNECTED" if status.running else "CONNECT PLAYIT")

    def set_setup_active(self, active: bool, message=""):
        self.connect_button.setEnabled(not active)
        self.check_button.setEnabled(not active)
        self.cancel_button.setVisible(active)
        if message:
            self.setup_status.setText(message)

    def set_target(self, target: TunnelTarget | None, server_name=""):
        while self.target_rows.count():
            item = self.target_rows.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        if target is None:
            self.target_summary.setText("Choose a server from My servers to fill in its safe local target.")
            self.target_note.clear()
            return

        self.target_summary.setText(f"{server_name} is ready to use as a Playit tunnel target.")
        for name, value in (
            ("Tunnel type", target.tunnel_type),
            ("Local address", target.local_address),
            ("Local host", target.local_host),
            ("Local port", str(target.local_port)),
        ):
            row = QHBoxLayout()
            label = QLabel(f"{name}: {value}")
            label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            row.addWidget(label, 1)
            copy = self._button("Copy", lambda checked=False, text=value: QApplication.clipboard().setText(text))
            copy.setMaximumWidth(90)
            row.addWidget(copy)
            wrapper = QWidget()
            wrapper.setLayout(row)
            self.target_rows.addWidget(wrapper)
        self.target_note.setText(target.note)


def make_guide(button_class=QPushButton):
    return PlayitGuide(button_class)
