"""Typed native-oracle failures whose observations remain useful evidence."""


class NativeIntervalError(RuntimeError):
    def __init__(self, message, job):
        super().__init__(message)
        self.job = job
