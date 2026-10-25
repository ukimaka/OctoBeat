# OctoBeat - музыкальный плеер
# Copyright (C) 2026 ukimaka
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""HTTP-клиент для взаимодействия с backend API музыкального плеера."""

from __future__ import annotations

from typing import Any

import requests


DEFAULT_BASE_URL = "https://octopus-music-server.onrender.com"
DEFAULT_TIMEOUT = 10.0


class ApiError(Exception):
    """Ошибка сети или HTTP-запроса с понятным пользователю текстом."""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class ApiClient:
    """Минимальный клиент REST API: авторизация и профиль."""

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        token: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    # ------------------------------------------------------------------
    #  Внутренние методы
    # ------------------------------------------------------------------
    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    @staticmethod
    def _error_text(response: requests.Response) -> str:
        """Достаёт читаемое описание ошибки из ответа FastAPI."""
        try:
            payload = response.json()
        except ValueError:
            payload = None

        detail = payload.get("detail") if isinstance(payload, dict) else None

        if isinstance(detail, str):
            return detail

        if isinstance(detail, list):
            messages = []
            for item in detail:
                if not isinstance(item, dict):
                    messages.append(str(item))
                    continue
                location = ".".join(
                    str(part) for part in item.get("loc", ()) if part != "body"
                )
                message = item.get("msg", "Invalid value")
                messages.append(f"{location}: {message}" if location else message)
            if messages:
                return "; ".join(messages)

        return f"HTTP {response.status_code}: {response.reason}"

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            response = requests.request(
                method,
                self._url(path),
                timeout=self.timeout,
                **kwargs,
            )
        except requests.Timeout as exc:
            raise ApiError(
                "The server did not respond in time. Please try again."
            ) from exc
        except requests.ConnectionError as exc:
            raise ApiError(
                "Cannot connect to the server. Make sure the backend is running."
            ) from exc
        except requests.RequestException as exc:
            raise ApiError(f"Network error: {exc}") from exc

        if response.status_code >= 400:
            raise ApiError(self._error_text(response), response.status_code)

        if not response.content:
            return {}

        try:
            return response.json()
        except ValueError as exc:
            raise ApiError(
                "The server returned an invalid response.",
                response.status_code,
            ) from exc

    def _request_list(
        self, method: str, path: str, **kwargs: Any
    ) -> list[dict[str, Any]]:
        """Выполняет запрос и проверяет, что сервер вернул список."""
        data = self._request(method, path, **kwargs)
        if not isinstance(data, list):
            raise ApiError("The server returned an unexpected response.")
        return data

    def _auth_headers(self) -> dict[str, str]:
        if not self.token:
            raise ApiError("Authorization token is missing.", 401)
        return {"Authorization": f"Bearer {self.token}"}

    def _fetch_static_bytes(self, path: str | None) -> bytes | None:
        """Downloads a file from the server's static storage."""
        if not path:
            return None
        url = (
            path
            if path.startswith(("http://", "https://"))
            else self._url(path)
        )
        print(f"[API] Downloading avatar from: {url}")
        try:
            response = requests.get(url, timeout=self.timeout)
        except requests.RequestException as exc:
            print(f"[API] Download failed: {exc}")
            return None
        print(f"[API] Status: {response.status_code}")
        if response.status_code >= 400 or not response.content:
            return None
        return response.content

    # ------------------------------------------------------------------
    #  Публичные методы
    # ------------------------------------------------------------------
    def register(self, username: str, password: str) -> dict[str, Any]:
        """Регистрирует пользователя и возвращает данные созданного профиля."""
        return self._request(
            "POST",
            "/auth/register",
            json={"username": username, "password": password},
        )

    def login(self, username: str, password: str) -> dict[str, Any]:
        """Авторизует пользователя и сохраняет access_token в self.token."""
        data = self._request(
            "POST",
            "/auth/login",
            json={"username": username, "password": password},
        )
        token = data.get("access_token")
        if not isinstance(token, str) or not token:
            raise ApiError("The server response does not contain an access token.")
        self.token = token
        return data

    def get_me(self) -> dict[str, Any]:
        """Возвращает профиль текущего пользователя по сохранённому токену."""
        return self._request("GET", "/users/me", headers=self._auth_headers())

    def update_my_profile(self, data: dict[str, Any]) -> dict[str, Any]:
        """Обновляет профиль текущего пользователя на сервере."""
        return self._request(
            "PUT",
            "/users/me/profile",
            json=data,
            headers=self._auth_headers(),
        )

    def get_user_profile(self, user_id: int) -> dict[str, Any]:
        """Возвращает профиль другого пользователя по его ID.

        Если сервер вернул пути к аватарке/баннеру, они скачиваются
        и добавляются в результат как ``avatar_bytes``/``banner_bytes``.
        """
        profile = self._request(
            "GET",
            f"/users/{user_id}/profile",
            headers=self._auth_headers(),
        )
        print(f"[API] PROFILE DATA FROM SERVER: {profile}")
        avatar = self._fetch_static_bytes(profile.get("avatar_path"))
        if avatar is not None:
            profile["avatar_bytes"] = avatar
        banner = self._fetch_static_bytes(profile.get("banner_path"))
        if banner is not None:
            profile["banner_bytes"] = banner
        return profile

    # ------------------------------------------------------------------
    #  Друзья
    # ------------------------------------------------------------------
    def search_users(self, query: str) -> list[dict[str, Any]]:
        """Ищет пользователей по username."""
        return self._request_list(
            "GET",
            "/users/search",
            params={"q": query},
            headers=self._auth_headers(),
        )

    def send_friend_request(self, user_id: int) -> dict[str, Any]:
        """Отправляет заявку в друзья."""
        return self._request(
            "POST",
            f"/friends/request/{user_id}",
            headers=self._auth_headers(),
        )

    def get_incoming_requests(self) -> list[dict[str, Any]]:
        """Возвращает входящие заявки в друзья."""
        return self._request_list(
            "GET",
            "/friends/requests/incoming",
            headers=self._auth_headers(),
        )

    def accept_friend_request(self, user_id: int) -> dict[str, Any]:
        """Принимает входящую заявку от пользователя user_id."""
        return self._request(
            "POST",
            f"/friends/accept/{user_id}",
            headers=self._auth_headers(),
        )

    def reject_friend_request(self, user_id: int) -> dict[str, Any]:
        """Отклоняет входящую заявку от пользователя user_id."""
        return self._request(
            "DELETE",
            f"/friends/reject/{user_id}",
            headers=self._auth_headers(),
        )

    def get_friends(self) -> list[dict[str, Any]]:
        """Возвращает список друзей текущего пользователя."""
        return self._request_list(
            "GET",
            "/friends",
            headers=self._auth_headers(),
        )

    # ------------------------------------------------------------------
    #  Плейлисты
    # ------------------------------------------------------------------
    def get_user_playlists(self, user_id: int) -> list[dict[str, Any]]:
        """Публичные плейлисты пользователя (для чужого профиля)."""
        return self._request_list(
            "GET",
            f"/users/{user_id}/playlists",
            headers=self._auth_headers(),
        )

    def get_playlist(self, playlist_id: int) -> dict[str, Any]:
        """Плейлист вместе с треками."""
        return self._request(
            "GET",
            f"/playlists/{playlist_id}",
            headers=self._auth_headers(),
        )
