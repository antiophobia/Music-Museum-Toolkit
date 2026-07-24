"""
Music Museum Toolkit
Helper Functions
Version 0.1 Foundation
"""


def chunk_list(items, chunk_size):
    """
    Split a list into chunks of a fixed size.
    """

    for i in range(0, len(items), chunk_size):
        yield items[i:i + chunk_size]