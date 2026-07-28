from services import get_user, create_user


def handle_get_user(request):
    return get_user(request.id)


def handle_create_user(request):
    return create_user(request.name)
