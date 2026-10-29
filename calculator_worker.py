# -*- coding: utf-8 -*-
"""Run workday calculations on a dedicated Qt thread."""

import logging

from PySide6.QtCore import QThread, Signal

import workday_calculation

logger = logging.getLogger("prison_calc")


class CalculatorWorker(QThread):
    """Execute the date-range calculation without blocking the window thread."""

    finished_ok = Signal(int)
    failed = Signal()

    def __init__(self, begin, end, parent=None):
        super().__init__(parent)
        self.begin = begin
        self.end = end

    def run(self):
        try:
            days = workday_calculation.remaining_workdays(
                last_day=self.end, start=self.begin)
        except Exception:
            logger.exception("Workday calculation failed")
            self.failed.emit()
            return
        self.finished_ok.emit(days)
