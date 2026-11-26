"""Business Developer management API (Admin only).

A Business Developer is a user in the "BD Manager" group. Admins can list them,
add new ones, edit their name and email, switch them active or inactive, and set
a new password. Users are never deleted: their notes and stage changes stay
attributed to them, and an inactive user simply cannot sign in.

GET    /api/v1/business-developers/                  ?q=&status=active|inactive
POST   /api/v1/business-developers/
PATCH  /api/v1/business-developers/<id>/
POST   /api/v1/business-developers/<id>/reset-password/
"""
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction
from django.db.models import Count, Q
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.permissions import IsAdmin

User = get_user_model()

NAME_MAX = 150


def bd_queryset():
    """Users whose role is BD Manager. Admins and superusers are never listed."""
    return (
        User.objects.filter(groups__name=settings.ROLE_BD_MANAGER)
        .exclude(is_superuser=True)
        .exclude(groups__name=settings.ROLE_ADMIN)
        .annotate(
            stage_change_count=Count("opportunitystagechange", distinct=True),
            note_count=Count("opportunitynote", distinct=True),
        )
        .order_by("first_name", "last_name", "username")
    )


def serialize_bd(user):
    changes = getattr(user, "stage_change_count", None)
    notes = getattr(user, "note_count", None)
    if changes is None:
        changes = user.opportunitystagechange_set.count()
    if notes is None:
        notes = user.opportunitynote_set.count()
    return {
        "id": user.pk,
        "username": user.get_username(),
        "first_name": user.first_name,
        "last_name": user.last_name,
        "full_name": user.get_full_name() or user.get_username(),
        "email": user.email,
        "is_active": user.is_active,
        "date_joined": user.date_joined.isoformat() if user.date_joined else None,
        "last_login": user.last_login.isoformat() if user.last_login else None,
        "stage_changes": changes,
        "notes": notes,
    }


def _clean_text(data, field, errors, required=False, label=None):
    value = data.get(field)
    value = "" if value is None else str(value).strip()
    label = label or field.replace("_", " ")
    if required and not value:
        errors[field] = [f"Enter the {label}."]
    elif len(value) > NAME_MAX:
        errors[field] = [f"Use {NAME_MAX} characters or fewer."]
    return value


def _clean_email(data, errors, exclude_pk=None):
    email = str(data.get("email") or "").strip()
    if not email:
        errors["email"] = ["Enter the email address."]
        return email
    try:
        validate_email(email)
    except ValidationError:
        errors["email"] = ["Enter a valid email address."]
        return email
    clash = User.objects.filter(email__iexact=email)
    if exclude_pk:
        clash = clash.exclude(pk=exclude_pk)
    if clash.exists():
        errors["email"] = ["Another user already has this email address."]
    return email


def _check_password(password, user, errors, field="password"):
    if not password:
        errors[field] = ["Enter a password."]
        return
    try:
        validate_password(password, user=user)
    except ValidationError as exc:
        errors[field] = list(exc.messages)


class BusinessDeveloperListCreateView(APIView):
    permission_classes = [IsAdmin]

    def get(self, request):
        qs = bd_queryset()
        status_param = (request.query_params.get("status") or "").lower()
        if status_param == "active":
            qs = qs.filter(is_active=True)
        elif status_param == "inactive":
            qs = qs.filter(is_active=False)
        q = (request.query_params.get("q") or "").strip()
        if q:
            qs = qs.filter(
                Q(username__icontains=q)
                | Q(first_name__icontains=q)
                | Q(last_name__icontains=q)
                | Q(email__icontains=q)
            )
        results = [serialize_bd(u) for u in qs]
        return Response({"count": len(results), "results": results})

    def post(self, request):
        data = request.data
        errors = {}
        first = _clean_text(data, "first_name", errors, required=True, label="first name")
        last = _clean_text(data, "last_name", errors, required=True, label="last name")
        username = _clean_text(data, "username", errors, required=True, label="username")
        email = _clean_email(data, errors)
        if username and "username" not in errors:
            try:
                User._meta.get_field("username").run_validators(username)
            except ValidationError as exc:
                errors["username"] = list(exc.messages)
            else:
                if User.objects.filter(username__iexact=username).exists():
                    errors["username"] = ["This username is already taken."]
        password = str(data.get("password") or "")
        candidate = User(username=username, first_name=first, last_name=last, email=email)
        _check_password(password, candidate, errors)
        if errors:
            return Response(errors, status=status.HTTP_400_BAD_REQUEST)

        with transaction.atomic():
            user = User.objects.create_user(
                username=username, email=email, password=password,
                first_name=first, last_name=last,
            )
            group, _ = Group.objects.get_or_create(name=settings.ROLE_BD_MANAGER)
            user.groups.add(group)
        return Response(serialize_bd(user), status=status.HTTP_201_CREATED)


class BusinessDeveloperDetailView(APIView):
    permission_classes = [IsAdmin]

    def _get(self, pk):
        return bd_queryset().filter(pk=pk).first()

    def patch(self, request, pk):
        user = self._get(pk)
        if user is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        data = request.data
        errors = {}
        updates = {}
        if "first_name" in data:
            updates["first_name"] = _clean_text(data, "first_name", errors, required=True, label="first name")
        if "last_name" in data:
            updates["last_name"] = _clean_text(data, "last_name", errors, required=True, label="last name")
        if "email" in data:
            updates["email"] = _clean_email(data, errors, exclude_pk=user.pk)
        if "is_active" in data:
            value = data.get("is_active")
            if not isinstance(value, bool):
                errors["is_active"] = ["Send true or false."]
            else:
                if value is False and user.pk == request.user.pk:
                    errors["is_active"] = ["You cannot deactivate your own account."]
                updates["is_active"] = value
        if errors:
            return Response(errors, status=status.HTTP_400_BAD_REQUEST)
        if updates:
            for key, value in updates.items():
                setattr(user, key, value)
            user.save(update_fields=list(updates.keys()))
        return Response(serialize_bd(self._get(pk)))


class BusinessDeveloperPasswordView(APIView):
    permission_classes = [IsAdmin]

    def post(self, request, pk):
        user = bd_queryset().filter(pk=pk).first()
        if user is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        errors = {}
        password = str(request.data.get("password") or "")
        _check_password(password, user, errors)
        if errors:
            return Response(errors, status=status.HTTP_400_BAD_REQUEST)
        user.set_password(password)
        user.save(update_fields=["password"])
        return Response({"detail": "Password updated."})
