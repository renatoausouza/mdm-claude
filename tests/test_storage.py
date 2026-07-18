from mdm import storage


def test_saved_document_is_not_stored_as_plaintext_on_disk() -> None:
    plaintext = b"hello world, this is a document"
    document_id = "doc-1"

    path = storage.save_document(document_id, plaintext)

    with open(path, "rb") as f:
        raw_on_disk = f.read()
    assert raw_on_disk != plaintext


def test_read_document_recovers_original_bytes() -> None:
    plaintext = b"hello world, this is a document"
    document_id = "doc-2"

    storage.save_document(document_id, plaintext)
    recovered = storage.read_document(document_id)

    assert recovered == plaintext
