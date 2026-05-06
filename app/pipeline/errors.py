"""Pipeline-specific exceptions."""


class PipelineError(Exception):
    pass


class StageError(PipelineError):
    def __init__(self, message: str, stage: int):
        super().__init__(message)
        self.stage = stage
