from typing import Any


class Singleton(type):
    _instances: dict[Any, Any] = {}

    def __call__(cls: Any, *args: Any, **kwargs: Any) -> Any:
        if cls not in cls._instances:
            instance = super().__call__(*args, **kwargs)
            cls._instances[cls] = instance
        else:
            instance = cls._instances[cls]
            if hasattr(cls, "__allow_reinitialization") and cls.__allow_reinitialization:
                instance.__init__(*args, **kwargs)
        return instance
