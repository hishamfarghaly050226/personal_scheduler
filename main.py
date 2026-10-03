"""Entry point of the Personal Scheduler.   Run with:  python main.py"""

import sys

from PySide6.QtWidgets import QApplication, QMessageBox

from database import DatabaseError, DatabaseManager
from gui.main_window import MainWindow
from services import ReminderService, Scheduler


class Application:
    """Creates all objects and connects them (the 'composition root').

    Dependencies are passed in through constructors instead of being global:
        DatabaseManager -> Scheduler -> ReminderService -> MainWindow
    """

    def __init__(self) -> None:
        self._qt_app = QApplication(sys.argv)
        self._qt_app.setApplicationName("Personal Scheduler")
        self._qt_app.setStyle("Fusion")          # consistent look on every Windows version
        self._db: DatabaseManager | None = None
        self._window: MainWindow | None = None

    def run(self) -> int:
        try:
            self._db = DatabaseManager()         # creates data/scheduler.db when missing
        except DatabaseError as error:
            QMessageBox.critical(None, "Database error", str(error))
            return 1

        scheduler = Scheduler(self._db)
        reminder_service = ReminderService(scheduler)
        self._window = MainWindow(scheduler, reminder_service)
        self._window.show()

        exit_code = self._qt_app.exec()
        self._db.close()
        return exit_code


if __name__ == "__main__":
    sys.exit(Application().run())
