class ExtractionError(RuntimeError):
    pass


class UnsupportedDocumentType(ExtractionError):
    pass


class CorruptDocument(ExtractionError):
    pass
