from typing import Callable, Union, List, Dict, Any
import functools
import json
from uuid import UUID
from datetime import datetime

from fastapi import Request, Response
from redis.asyncio import Redis, ConnectionPool
from sqlalchemy.orm import class_mapper, DeclarativeBase

from app.core.exceptions import CacheIdentificationInferenceError

pool: ConnectionPool | None = None
client: Redis | None = None

def _serialize_sqlalchemy_object(obj: DeclarativeBase) -> Dict[str, Any]:
    """
    Serialize a SQLAlchemy DeclarativeBase object to a dictionary.

    Parameters
    ----------
    obj: DeclarativeBase
        The SQLAlchemy DeclarativeBase object to be serialized.
        
    Returns
    -------
    Dict[str, Any] 
        A dictionary containing the serialized attributes of the object.
    
    Note
    ----
        - Datetime objects are converted to ISO 8601 string format.
        - UUID objects are converted to strings before serializing to JSON.
    """
    if isinstance(obj, DeclarativeBase):
        data = {}
        for column in class_mapper(obj.__class__).columns:
            value = getattr(obj, column.name)

            if isinstance(value, datetime):
                value = value.isoformat()
            
            if isinstance(value, UUID):
                value = str(value)

            data[column.name] = value
        return data


def _infer_resource_id(kwargs: Dict[str, Any], resource_id_type: Union[type, str]) -> Union[None, int, str]:
    """
    Infer the resource ID from a dictionary of keyword arguments.

    Parameters
    ----------
    kwargs: Dict[str, Any] 
        A dictionary of keyword arguments.
    resource_id_type: Union[type, str] 
        The expected type of the resource ID, which can be an integer (int) or a string (str).
        
    Returns
    -------
    Union[None, int, str]
        The inferred resource ID. If it cannot be inferred or does not match the expected type, it returns None.

    Note
    ----
        - When `resource_id_type` is 'int', the function looks for an argument with the key 'id'.
        - When `resource_id_type` is 'str', it attempts to infer the resource ID as a string.
    """
    resource_id = None
    for arg_name, arg_value in kwargs.items():
        if isinstance(arg_value, resource_id_type):
            if (resource_id_type is int) and ("id" in arg_name):
                resource_id = arg_value
            
            elif (resource_id_type is int) and ("id" not in arg_name):
                pass

            elif resource_id_type is str:
                resource_id = arg_value 

    if resource_id is None:
        raise CacheIdentificationInferenceError

    return resource_id


def cache(key_prefix: str, resource_id_name: Any = None, expiration: int = 3600, resource_id_type: Union[type, List[type]] = int) -> Callable:
    """
    Cache decorator for FastAPI endpoints.

    This decorator allows you to cache the results of FastAPI endpoint functions, improving response times and reducing the load on the application by storing and retrieving data in a cache.

    Parameters
    ----------
    key_prefix: str
        A unique prefix to identify the cache key.
    resource_id: Any, optional
        The resource ID to be used in cache key generation. If not provided, it will be inferred from the endpoint's keyword arguments.
    expiration: int, optional
        The expiration time for cached data in seconds. Defaults to 3600 seconds (1 hour).
    resource_id_type: Union[type, List[type]], optional
        The expected type of the resource ID. This can be a single type (e.g., int) or a list of types (e.g., [int, str]). Defaults to int.

    Returns
    -------
    Callable
        A decorator function that can be applied to FastAPI endpoints.

    Example usage
    -------------

    ```python
    from fastapi import FastAPI, Request
    from my_module import cache  # Replace with your actual module and imports

    app = FastAPI()

    # Define a sample endpoint with caching
    @app.get("/sample/{resource_id}")
    @cache(key_prefix="sample_data", expiration=3600, resource_id_type=int)
    async def sample_endpoint(request: Request, resource_id: int):
        # Your endpoint logic here
        return {"data": "your_data"}
    ```

    This decorator caches the response data of the endpoint function using a unique cache key.
    The cached data is retrieved for GET requests, and the cache is invalidated for other types of requests.

    Note:
        - For caching lists of objects, ensure that the response is a list of objects, and the decorator will handle caching accordingly.
        - resource_id_type is used only if resource_id is not passed.
    """
    def wrapper(func: Callable) -> Callable:
        @functools.wraps(func)
        async def inner(request: Request, *args, **kwargs) -> Response:
            if resource_id_name:
                resource_id = kwargs[resource_id_name]
            else:
                resource_id = _infer_resource_id(kwargs=kwargs, resource_id_type=resource_id_type)
            
            cache_key = f"{key_prefix}:{resource_id}"
            
            if request.method == "GET":
                cached_data = await client.get(cache_key)
                if cached_data:
                    return json.loads(cached_data.decode())
            
            result = await func(request, *args, **kwargs)

            if request.method == "GET":
                if isinstance(result, list):
                    serialized_data = json.dumps(
                        [_serialize_sqlalchemy_object(obj) for obj in result]
                    )
                else:
                    serialized_data = json.dumps(
                        _serialize_sqlalchemy_object(result)
                    )
                
                await client.set(cache_key, serialized_data)
                await client.expire(cache_key, expiration)
            else:
                await client.delete(cache_key)
            
            return result
        
        return inner

    return wrapper
