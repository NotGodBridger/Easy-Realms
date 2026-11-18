import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import sys
import unittest
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QProcess,Qt
from PySide6.QtTest import QTest
from app import Window

class ConsoleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def setUp(self):self.window=Window(offline=True)
    def tearDown(self):
        p=self.window.process
        if p.state()!=QProcess.NotRunning:p.kill();p.waitForFinished(3000)
        self.window.close();self.window.deleteLater()
    def test_real_process_receives_command(self):
        w=self.window
        self.assertFalse(w.command_input.isEnabled())
        w.process.start(sys.executable,['-u','-c','import sys\nfor line in sys.stdin: print("RECEIVED:"+line.strip(),flush=True)'])
        self.assertTrue(w.process.waitForStarted(5000));self.assertTrue(w.command_input.isEnabled())
        w.command_input.setText('/say hello');w.send.click()
        self.assertTrue(w.process.waitForReadyRead(5000))
        self.assertIn('RECEIVED:say hello',w.console.toPlainText())
        self.assertEqual(w.command_input.text(),'')
        w.command_input.setText('list');w.command_input.returnPressed.emit()
        self.assertTrue(w.process.waitForReadyRead(5000))
        self.assertIn('RECEIVED:list',w.console.toPlainText())
        QTest.keyClick(w.command_input,Qt.Key_Up);self.assertEqual(w.command_input.text(),'list')
        QTest.keyClick(w.command_input,Qt.Key_Up);self.assertEqual(w.command_input.text(),'say hello')
        w.process.kill();w.process.waitForFinished(3000)
        self.assertFalse(w.send.isEnabled());self.assertFalse(w.command_input.isEnabled())
    def test_stopped_does_not_send(self):
        w=self.window;w.command_input.setText('stop');w.send_command()
        self.assertEqual(w.command_input.history,[])
        self.assertIn('Start the server',w.status.text())
    def test_restart_requests_clean_stop(self):
        w=self.window
        w.process.start(sys.executable,['-u','-c','import sys\nfor line in sys.stdin:\n print("RECEIVED:"+line.strip(),flush=True)\n if line.strip()=="stop": break'])
        self.assertTrue(w.process.waitForStarted(5000))
        w.restart_server()
        self.assertTrue(w.restart_pending)
        self.assertTrue(w.process.waitForReadyRead(5000))
        self.assertIn('RECEIVED:stop',w.console.toPlainText())
        w.restart_pending=False
        w.process.waitForFinished(5000)

if __name__=='__main__':unittest.main()
