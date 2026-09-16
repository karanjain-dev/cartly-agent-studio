class ServiceError(Exception):
    def __init__(self, code, message, status=400, rules=None):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status
        self.rules = rules or []

    def response(self):
        return {"ok": False, "error": {"code": self.code, "message": self.message, "rules": self.rules}}
