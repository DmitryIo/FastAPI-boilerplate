class CacheIdentificationInferenceError(Exception):
    def __init__(self, message="Could not infer id for resource being cached."):
        self.message = message
        super().__init__(self.message)
