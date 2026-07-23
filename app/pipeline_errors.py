from __future__ import annotations


class ServiceError(Exception):
    ...


class PipelineStartupError(ServiceError):
    ...


class WorkerError(ServiceError):
    ...


class PipelineTimeoutError(ServiceError):
    ...


class TranslationError(ServiceError):
    ...


class TTSError(ServiceError):
    ...


class STTError(ServiceError):
    ...


class AudioDeviceError(ServiceError):
    ...
