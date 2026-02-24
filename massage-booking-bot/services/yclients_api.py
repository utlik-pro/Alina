"""YClients REST API v2.0 Client for Crystal Lab Booking Bot

API Documentation: https://developer.yclients.com
Apiary Docs: https://yclients.docs.apiary.io

Authentication:
- Partner token (Bearer): obtained from YClients partner program
- User token: obtained via POST /auth with login/password
- Header format: Authorization: Bearer {partner_token}, User {user_token}
"""

import httpx
from typing import Optional, Dict, Any, List
from datetime import date, datetime
from loguru import logger


class YClientsClient:
    """Async client for YClients REST API v2.0"""

    BASE_URL = "https://api.yclients.com/api/v1"

    def __init__(
        self,
        partner_token: str,
        company_id: str,
        user_token: str = "",
        login: str = "",
        password: str = "",
    ):
        self.partner_token = partner_token
        self.company_id = company_id
        self.user_token = user_token
        self.login = login
        self.password = password
        self._client: Optional[httpx.AsyncClient] = None

    @property
    def headers(self) -> Dict[str, str]:
        h = {
            "Accept": "application/vnd.yclients.v2+json",
            "Content-Type": "application/json",
        }
        if self.user_token:
            h["Authorization"] = f"Bearer {self.partner_token}, User {self.user_token}"
        else:
            h["Authorization"] = f"Bearer {self.partner_token}"
        return h

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=30.0)
        return self._client

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def _request(
        self, method: str, endpoint: str, json_data: Dict = None, params: Dict = None
    ) -> Dict[str, Any]:
        """Make API request and return parsed response."""
        client = await self._get_client()
        url = f"{self.BASE_URL}/{endpoint}"

        try:
            response = await client.request(
                method, url, headers=self.headers, json=json_data, params=params
            )
            response.raise_for_status()
            data = response.json()

            if not data.get("success", True):
                logger.error(f"YClients API error: {data.get('meta', {}).get('message', 'Unknown error')}")

            return data

        except httpx.HTTPStatusError as e:
            logger.error(f"YClients API {e.response.status_code}: {e.response.text}")
            raise
        except Exception as e:
            logger.error(f"YClients API request failed: {e}")
            raise

    # ── Authentication ────────────────────────────────────────────────

    async def authenticate(self, login: str = "", password: str = "") -> str:
        """Authenticate and get user token.

        POST /auth
        Returns user_token for subsequent requests.
        """
        login = login or self.login
        password = password or self.password

        data = await self._request("POST", "auth", json_data={
            "login": login,
            "password": password,
        })
        self.user_token = data.get("data", {}).get("user_token", "")
        logger.info("YClients authentication successful")
        return self.user_token

    # ── Clients ───────────────────────────────────────────────────────

    async def search_client(self, phone: str) -> Optional[Dict]:
        """Search client by phone number.

        GET /clients/{company_id}?phone={phone}
        """
        data = await self._request(
            "GET", f"clients/{self.company_id}",
            params={"phone": phone}
        )
        clients = data.get("data", [])
        if clients:
            logger.info(f"Found client by phone {phone}: {clients[0].get('name', 'N/A')}")
            return clients[0]
        logger.info(f"No client found for phone {phone}")
        return None

    async def create_client(
        self,
        name: str,
        phone: str,
        email: str = "",
        comment: str = "",
    ) -> Dict:
        """Create a new client.

        POST /clients/{company_id}
        """
        payload = {
            "name": name,
            "phone": phone,
        }
        if email:
            payload["email"] = email
        if comment:
            payload["comment"] = comment

        data = await self._request("POST", f"clients/{self.company_id}", json_data=payload)
        logger.info(f"Created client: {name} ({phone})")
        return data.get("data", {})

    async def get_client(self, client_id: int) -> Dict:
        """Get client by ID.

        GET /client/{company_id}/{client_id}
        """
        data = await self._request("GET", f"client/{self.company_id}/{client_id}")
        return data.get("data", {})

    # ── Visit History ─────────────────────────────────────────────────

    async def get_client_visits(self, client_id: int) -> List[Dict]:
        """Get client visit history.

        GET /records/{company_id}?client_id={client_id}
        """
        data = await self._request(
            "GET", f"records/{self.company_id}",
            params={"client_id": client_id}
        )
        visits = data.get("data", [])
        logger.info(f"Client {client_id}: {len(visits)} visits found")
        return visits

    # ── Services ──────────────────────────────────────────────────────

    async def get_services(self, staff_id: int = None) -> List[Dict]:
        """Get available services.

        GET /services/{company_id}
        Optional: filter by staff_id
        """
        params = {}
        if staff_id:
            params["staff_id"] = staff_id

        data = await self._request(
            "GET", f"services/{self.company_id}", params=params
        )
        services = data.get("data", {}).get("services", [])
        logger.info(f"Loaded {len(services)} services")
        return services

    # ── Staff ─────────────────────────────────────────────────────────

    async def get_staff(self) -> List[Dict]:
        """Get list of staff/masters.

        GET /staff/{company_id}
        """
        data = await self._request("GET", f"staff/{self.company_id}")
        staff = data.get("data", [])
        logger.info(f"Loaded {len(staff)} staff members")
        return staff

    async def get_staff_member(self, staff_id: int) -> Dict:
        """Get staff member details.

        GET /staff/{company_id}/{staff_id}
        """
        data = await self._request("GET", f"staff/{self.company_id}/{staff_id}")
        return data.get("data", {})

    # ── Available Time Slots ──────────────────────────────────────────

    async def get_available_dates(
        self, staff_id: int = None, service_ids: List[int] = None
    ) -> List[str]:
        """Get available booking dates.

        GET /book_dates/{company_id}
        Returns list of date strings: ["2026-03-01", "2026-03-02", ...]
        """
        params = {}
        if staff_id:
            params["staff_id"] = staff_id
        if service_ids:
            params["service_ids[]"] = service_ids

        data = await self._request(
            "GET", f"book_dates/{self.company_id}", params=params
        )
        dates = data.get("data", {}).get("booking_dates", [])
        logger.info(f"Available dates: {len(dates)}")
        return dates

    async def get_available_times(
        self,
        staff_id: int,
        booking_date: str,
        service_ids: List[int] = None,
    ) -> List[Dict]:
        """Get available time slots for a given date and staff member.

        GET /book_times/{company_id}/{staff_id}/{date}
        Returns list of time slots: [{"time": "10:00", "seance_length": 3600}, ...]
        """
        params = {}
        if service_ids:
            params["service_ids[]"] = service_ids

        data = await self._request(
            "GET", f"book_times/{self.company_id}/{staff_id}/{booking_date}",
            params=params,
        )
        times = data.get("data", [])
        logger.info(f"Available times for {booking_date}: {len(times)} slots")
        return times

    # ── Bookings / Records ────────────────────────────────────────────

    async def create_booking(
        self,
        staff_id: int,
        service_ids: List[int],
        booking_datetime: str,
        client_phone: str,
        client_name: str = "",
        client_email: str = "",
        comment: str = "",
        send_sms: bool = False,
    ) -> Dict:
        """Create a new booking/appointment.

        POST /book_record/{company_id}

        Args:
            staff_id: ID of the staff member
            service_ids: List of service IDs to book
            booking_datetime: ISO format datetime "2026-03-01T14:00:00"
            client_phone: Client phone number
            client_name: Client name
            client_email: Client email
            comment: Booking comment
            send_sms: Whether to send SMS notification
        """
        appointments = []
        for service_id in service_ids:
            appointments.append({
                "id": service_id,
                "staff_id": staff_id,
                "datetime": booking_datetime,
            })

        payload = {
            "phone": client_phone,
            "fullname": client_name,
            "email": client_email,
            "comment": comment,
            "type": "mobile",
            "notify_by_sms": 1 if send_sms else 0,
            "notify_by_email": 0,
            "appointments": appointments,
        }

        data = await self._request(
            "POST", f"book_record/{self.company_id}", json_data=payload
        )
        logger.info(f"Booking created for {client_name} ({client_phone})")
        return data.get("data", {})

    async def get_booking(self, record_id: int) -> Dict:
        """Get booking details.

        GET /record/{company_id}/{record_id}
        """
        data = await self._request("GET", f"record/{self.company_id}/{record_id}")
        return data.get("data", {})

    async def update_booking(self, record_id: int, **fields) -> Dict:
        """Update booking fields.

        PUT /record/{company_id}/{record_id}
        """
        data = await self._request(
            "PUT", f"record/{self.company_id}/{record_id}", json_data=fields
        )
        logger.info(f"Booking {record_id} updated")
        return data.get("data", {})

    async def delete_booking(self, record_id: int) -> bool:
        """Delete/cancel a booking.

        DELETE /record/{company_id}/{record_id}
        """
        data = await self._request("DELETE", f"record/{self.company_id}/{record_id}")
        logger.info(f"Booking {record_id} deleted")
        return data.get("success", False)

    # ── Convenience Methods ───────────────────────────────────────────

    async def find_or_create_client(self, phone: str, name: str = "") -> Dict:
        """Search for client by phone, create if not found."""
        client = await self.search_client(phone)
        if client:
            return client
        if name:
            return await self.create_client(name=name, phone=phone)
        return await self.create_client(name="New Client", phone=phone)

    async def check_availability(
        self,
        booking_date: str,
        service_ids: List[int] = None,
    ) -> List[Dict]:
        """Check all available staff and times for a date.

        Returns list of {staff_id, staff_name, available_times}.
        """
        staff_list = await self.get_staff()
        availability = []

        for staff in staff_list:
            try:
                times = await self.get_available_times(
                    staff_id=staff["id"],
                    booking_date=booking_date,
                    service_ids=service_ids,
                )
                if times:
                    availability.append({
                        "staff_id": staff["id"],
                        "staff_name": staff.get("name", ""),
                        "available_times": times,
                    })
            except Exception as e:
                logger.debug(f"No availability for staff {staff['id']}: {e}")

        return availability
