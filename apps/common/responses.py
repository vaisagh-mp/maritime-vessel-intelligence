from rest_framework.response import Response


def success(data=None, status=200, **extra):
    payload = {"success": True}
    if data is not None:
        payload["data"] = data
    payload.update(extra)
    return Response(payload, status=status)


def error(message, status=400, **extra):
    payload = {"success": False, "detail": message}
    payload.update(extra)
    return Response(payload, status=status)
