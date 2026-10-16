class BusinessRuleError(Exception):
    status_code = 400
    code = "business_rule"

    def __init__(self, message, code=None, status_code=None):
        super().__init__(message)
        self.message = message
        if code:
            self.code = code
        if status_code:
            self.status_code = status_code


class InsufficientStock(BusinessRuleError):
    status_code = 409
    code = "insufficient_stock"


class SubscriptionLimitReached(BusinessRuleError):
    status_code = 403
    code = "subscription_limit"
