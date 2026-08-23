class FakeTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.writes = []

    def write(self, payload: bytes) -> None:
        self.writes.append(payload)

    def read_line(self) -> bytes:
        if not self.responses:
            raise AssertionError("FakeTransport: no more responses queued")
        return self.responses.pop(0)
