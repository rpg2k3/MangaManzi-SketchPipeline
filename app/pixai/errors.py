"""PixAI-specific exceptions."""


class PixAIError(Exception):
    pass


class PixAIAuthError(PixAIError):
    pass


class PixAITimeoutError(PixAIError):
    pass


class PixAITaskFailedError(PixAIError):
    def __init__(self, message: str, raw_task: dict | None = None):
        super().__init__(message)
        self.raw_task = raw_task
