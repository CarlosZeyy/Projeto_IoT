"""Errors raised by qc_preprocess."""


class InvalidImageError(ValueError):
    """The input is not a decodable JPEG/PNG image within the accepted limits."""
