#!/usr/bin/env python3
"""Crystal Lab — Automated Test Agent.

Тестирует ИИ агента через Telegram API, имитируя реальных клиентов.
Прогоняет все ключевые сценарии и проверяет ответы.

Usage:
    python3.11 tests/test_agent.py                    # Run all tests
    python3.11 tests/test_agent.py body_massage       # Run specific test
    python3.11 tests/test_agent.py --list              # List available tests
"""

import asyncio
import sys
import time
import re
from typing import List, Tuple, Optional
from aiogram import Bot

# Bot config
BOT_TOKEN = "8080121464:AAGbeVoUh-62mxcMuPYbIhh7RQV1sJAxsB0"
# Test from a different user — we'll send commands as the bot reads them
# Actually, we need to send messages AS a user to the bot.
# The simplest way: use the bot's own sendMessage to itself won't work.
# Instead: we'll test the internal pipeline directly.

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from agents.booking_agent import BookingAgent
from dialog_context import DialogContext
from services.yclients_service import YClientsService
from datetime import datetime, timedelta


class TestResult:
    def __init__(self, name: str):
        self.name = name
        self.steps: List[Tuple[str, str, bool, str]] = []  # (input, output, passed, reason)

    def add_step(self, user_input: str, bot_output: str, passed: bool, reason: str = ""):
        self.steps.append((user_input, bot_output, passed, reason))

    @property
    def passed(self):
        return all(s[2] for s in self.steps)

    def summary(self):
        status = "✅ PASS" if self.passed else "❌ FAIL"
        lines = [f"\n{status} — {self.name}"]
        for i, (inp, out, ok, reason) in enumerate(self.steps, 1):
            icon = "✅" if ok else "❌"
            out_preview = out[:100].replace('\n', ' ')
            lines.append(f"  {icon} Step {i}: '{inp[:50]}' → '{out_preview}'")
            if not ok and reason:
                lines.append(f"     ⚠️ {reason}")
        return "\n".join(lines)


class TestAgent:
    """Automated test agent for Crystal Lab bot."""

    def __init__(self):
        self.agent = BookingAgent()
        self.yclients = YClientsService()

    def _new_context(self) -> dict:
        """Create fresh dialog context as dict."""
        ctx = DialogContext(user_id=99999)
        ctx.state = "consulting"
        return ctx

    async def _send(self, message: str, context) -> str:
        """Send message to agent and get response."""
        # Add to context history
        context.recent_messages.append({"role": "user", "content": message})
        response = await self.agent.process_message(message, context)
        if response:
            context.recent_messages.append({"role": "assistant", "content": response})
        return response or ""

    # ═══════════════════════════════════════
    # TEST SCENARIOS
    # ═══════════════════════════════════════

    async def test_body_massage_booking(self) -> TestResult:
        """Full body massage booking flow."""
        r = TestResult("Body Massage — Full Booking Flow")
        ctx = self._new_context()

        # Step 1: Greeting
        out = await self._send("Hi", ctx)
        r.add_step("Hi", out,
                    "service" in out.lower() or "interested" in out.lower() or "dear" in out.lower(),
                    "Should greet and ask about services")

        # Step 2: Ask for body massage
        out = await self._send("Body massage", ctx)
        r.add_step("Body massage", out,
                    "350" in out and "aed" in out.lower(),
                    "Should show body massage prices (350 AED)")

        # Step 3: Choose duration
        out = await self._send("60 min", ctx)
        r.add_step("60 min", out,
                    "location" in out.lower() or "time" in out.lower() or "available" in out.lower(),
                    "Should ask for location or offer times")

        # Step 4: Give location
        out = await self._send("Abu Dhabi, Al Raha", ctx)
        r.add_step("Abu Dhabi, Al Raha", out,
                    any(t in out for t in ["9:00", "10:00", "12:00", "available"]) or "time" in out.lower(),
                    "Should offer available time slots")

        # Step 5: Choose time
        out = await self._send("Tomorrow 10am", ctx)
        r.add_step("10am", out,
                    "name" in out.lower() or "good name" in out.lower(),
                    "Should ask for name")

        # Step 6: Give name
        out = await self._send("Sarah", ctx)
        r.add_step("Sarah", out,
                    "whatsapp" in out.lower() or "phone" in out.lower() or "number" in out.lower(),
                    "Should ask for WhatsApp number")

        # Step 7: Give phone
        out = await self._send("+971 55 123 4567", ctx)
        r.add_step("+971 55 123 4567", out,
                    "cash" in out.lower() or "pay" in out.lower() or "transfer" in out.lower(),
                    "Should ask about payment")

        # Step 8: Payment
        out = await self._send("Cash", ctx)
        r.add_step("Cash", out,
                    "booked" in out.lower() or "✅" in out,
                    "Should confirm booking with ✅")

        return r

    async def test_face_massage(self) -> TestResult:
        """Face massage inquiry."""
        r = TestResult("Face Massage — Price Inquiry")
        ctx = self._new_context()

        out = await self._send("Hi, I want face massage", ctx)
        r.add_step("Hi, I want face massage", out,
                    "370" in out and "aed" in out.lower(),
                    "Should show face massage price (370 AED)")

        return r

    async def test_cupping_distinction(self) -> TestResult:
        """Cupping — should explain two types."""
        r = TestResult("Cupping — Two Services Distinction")
        ctx = self._new_context()

        out = await self._send("I want cupping", ctx)
        r.add_step("I want cupping", out,
                    "275" in out and "350" in out,
                    "Should explain both: cupping offer 275 AED and body massage with cups 350 AED")

        return r

    async def test_manicure(self) -> TestResult:
        """Manicure inquiry."""
        r = TestResult("Manicure — Prices")
        ctx = self._new_context()

        out = await self._send("Hi, manicure please", ctx)
        r.add_step("Hi, manicure please", out,
                    "200" in out and "aed" in out.lower(),
                    "Should show Russian gelish mani price (200 AED)")

        return r

    async def test_lash_extensions(self) -> TestResult:
        """Lash extensions — Abu Dhabi only."""
        r = TestResult("Lash Extensions — Abu Dhabi Only Rule")
        ctx = self._new_context()

        out = await self._send("I want eyelash extensions, I'm in Al Ain", ctx)
        r.add_step("eyelash extensions in Al Ain", out,
                    "abu dhabi" in out.lower() or "only" in out.lower(),
                    "Should mention lash extensions only in Abu Dhabi")

        return r

    async def test_english_only(self) -> TestResult:
        """English by default, but switch when the client can't follow English (rule revised 2026-07-15)."""
        r = TestResult("Language — English default + switch")
        ctx = self._new_context()

        # A lone/casual foreign message is NOT a trigger → stay in English.
        out = await self._send("Привет, хочу массаж", ctx)
        has_cyrillic = bool(re.search('[а-яА-Я]', out))
        r.add_step("Привет, хочу массаж", out,
                    not has_cyrillic or "english" in out.lower(),
                    "Casual RU greeting → stay in English")

        # Client says they don't understand English → switch to Russian.
        ctx2 = self._new_context()
        await self._send("Hello, I want a massage", ctx2)
        out2 = await self._send("извините, я не понимаю по-английски, напишите на русском пожалуйста", ctx2)
        r.add_step("Я не понимаю по-английски…", out2,
                    bool(re.search('[а-яА-Я]', out2)),
                    "Client can't follow English → switch to Russian")

        return r

    async def test_arabic_response(self) -> TestResult:
        """Arabic → ask for English."""
        r = TestResult("Language — Arabic → Ask English")
        ctx = self._new_context()

        out = await self._send("مرحبا أريد حجز مساج", ctx)
        r.add_step("Arabic message", out,
                    "english" in out.lower(),
                    "Should ask client to write in English")

        return r

    async def test_man_rejection(self) -> TestResult:
        """Men should be politely rejected."""
        r = TestResult("Policy — Male Client Rejection")
        ctx = self._new_context()

        out = await self._send("Hi, I'm a man, can I book a massage?", ctx)
        r.add_step("I'm a man", out,
                    "female" in out.lower() or "women" in out.lower() or "sorry" in out.lower(),
                    "Should politely reject male clients")

        return r

    async def test_send_from_ad(self) -> TestResult:
        """Client clicks ad → sends 'send'."""
        r = TestResult("Ad Click — Just 'send'")
        ctx = self._new_context()

        out = await self._send("send", ctx)
        r.add_step("send", out,
                    "service" in out.lower() or "interested" in out.lower() or "body" in out.lower(),
                    "Should ask what service they're interested in")

        return r

    async def test_discount_request(self) -> TestResult:
        """Client asks for discount → Book a Friend."""
        r = TestResult("Discount Request → Book a Friend")
        ctx = self._new_context()

        out = await self._send("Hi, do you have any discounts? Too expensive", ctx)
        r.add_step("discount request", out,
                    "friend" in out.lower() or "trial" in out.lower() or "offer" in out.lower() or "350" in out,
                    "Should mention trial session or Book a Friend")

        return r

    async def test_no_fake_therapists(self) -> TestResult:
        """Agent should not invent therapist names."""
        r = TestResult("Therapists — No Fake Names")
        ctx = self._new_context()

        # Inject real slots into context
        tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        slots = await self.yclients.get_available_slots_summary(date=tomorrow)
        ctx.extra_system_info = f"\nREAL AVAILABLE SLOTS:\n{slots}\nUse ONLY these therapists."

        out = await self._send("Who are your therapists? I want to book", ctx)
        # Check for fake names as whole words (not substrings like "lana" in "svetlana")
        import re as _re
        fake_names = ["anna", "olga", "natasha", "irina", "julia", "katya", "diana"]
        has_fake = any(_re.search(rf'\b{name}\b', out.lower()) for name in fake_names)
        real_names = ["svetlana", "elena", "masha", "makhabat"]
        has_real = any(name in out.lower() for name in real_names)

        r.add_step("Who are your therapists?", out,
                    has_real and not has_fake,
                    f"Should use ONLY real names. Fake found: {has_fake}")

        return r

    async def test_yclients_api(self) -> TestResult:
        """Test YClients API connectivity."""
        r = TestResult("YClients API — Connectivity")

        staff = await self.yclients.get_staff()
        r.add_step("get_staff()", f"{len(staff)} staff members",
                    len(staff) > 0, "Should load staff from YClients")

        services = await self.yclients.get_services()
        r.add_step("get_services()", f"{len(services)} services",
                    len(services) > 0, "Should load services")

        tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        slots = await self.yclients.get_available_slots_summary(date=tomorrow)
        r.add_step("get_available_slots_summary()", slots[:100],
                    "Available" in slots and ":" in slots,
                    "Should return formatted slots")

        sid = await self.yclients.find_service_id("Body massage")
        r.add_step("find_service_id('Body massage')", str(sid),
                    sid is not None, "Should find body massage service")

        return r

    # ═══════════════════════════════════════
    # NEW TESTS
    # ═══════════════════════════════════════

    async def test_trial_session(self) -> TestResult:
        """Trial session offer for new clients."""
        r = TestResult("Trial Session — New Client Offer")
        ctx = self._new_context()

        out = await self._send("Hi, what do you have for new clients?", ctx)
        r.add_step("new client offer", out,
                    "350" in out and ("trial" in out.lower() or "80" in out),
                    "Should mention trial session 350 AED / 80 min")
        return r

    async def test_combo_body_face(self) -> TestResult:
        """Body + Face combo pricing."""
        r = TestResult("Combo Body+Face — Price 650 AED")
        ctx = self._new_context()

        out = await self._send("I want body and face massage together", ctx)
        r.add_step("body + face combo", out,
                    "650" in out,
                    "Should show combo price 650 AED")
        return r

    async def test_deep_facial_cleansing(self) -> TestResult:
        """Deep facial cleansing pricing."""
        r = TestResult("Deep Facial Cleansing — 420 AED")
        ctx = self._new_context()

        out = await self._send("I want deep facial cleansing", ctx)
        r.add_step("deep facial cleansing", out,
                    "420" in out,
                    "Should show price 420 AED")
        return r

    async def test_pmu(self) -> TestResult:
        """Permanent makeup pricing."""
        r = TestResult("Permanent Makeup — Prices")
        ctx = self._new_context()

        out = await self._send("How much is permanent makeup for lips?", ctx)
        r.add_step("PMU lips", out,
                    "900" in out,
                    "Should show PMU lips price 900 AED")
        return r

    async def test_medical_info(self) -> TestResult:
        """Medical info — should acknowledge and note."""
        r = TestResult("Medical Info — Acknowledge")
        ctx = self._new_context()

        await self._send("Hi, I want body massage", ctx)
        out = await self._send("I had cesarean surgery 2 months ago", ctx)
        r.add_step("cesarean info", out,
                    "therapist" in out.lower() or "thank" in out.lower() or "know" in out.lower(),
                    "Should acknowledge and say will inform therapist")
        return r

    async def test_next_week(self) -> TestResult:
        """Client says 'next week' — should acknowledge."""
        r = TestResult("'Next Week' — Acknowledge & Remind")
        ctx = self._new_context()

        await self._send("Hi, I want massage", ctx)
        out = await self._send("Maybe next week", ctx)
        r.add_step("next week", out,
                    "remind" in out.lower() or "ok" in out.lower() or "week" in out.lower(),
                    "Should say will remind")
        return r

    async def test_client_changes_mind(self) -> TestResult:
        """Client changes mind — use last answer."""
        r = TestResult("Change Mind — Use Last Answer")
        ctx = self._new_context()

        await self._send("I want body massage 60 min", ctx)
        out = await self._send("Actually 90 min please", ctx)
        r.add_step("change to 90 min", out,
                    "90" in out or "480" in out,
                    "Should switch to 90 min / 480 AED")
        return r

    async def test_pay_shortcut(self) -> TestResult:
        """Client says just 'pay' — should not re-ask."""
        r = TestResult("Payment Shortcut — 'pay' = cash")
        ctx = self._new_context()

        # Build context with all data collected
        ctx.booking_data["service_type"] = "Body massage"
        ctx.booking_data["service_duration"] = 60
        ctx.booking_data["price"] = 350.0
        ctx.booking_data["time"] = "10am"
        ctx.client_data["name"] = "Sarah"
        ctx.recent_messages = [
            {"role": "assistant", "content": "How would you like to pay? Cash - tax free / Bank transfer + 5% VAT"},
        ]

        out = await self._send("pay", ctx)
        r.add_step("just 'pay'", out,
                    "booked" in out.lower() or "✅" in out or "cash" in out.lower(),
                    "Should confirm booking or treat as cash, not re-ask")
        return r

    async def test_nails_specialist_only(self) -> TestResult:
        """Nails should show only nail specialists."""
        r = TestResult("Nails — Only Nail Specialists in Slots")
        ctx = self._new_context()

        tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        slots = await self.yclients.get_available_slots_summary(date=tomorrow, service_name="Russian gelish manicure")
        ctx.extra_system_info = f"\nREAL AVAILABLE SLOTS:\n{slots}\nUse ONLY these slots."

        out = await self._send("I want Russian manicure, when is available?", ctx)
        # Should NOT mention massage therapists (Svetlana, Masha, Makhabat)
        has_massage = any(n in out.lower() for n in ["svetlana", "masha", "makhabat"])
        r.add_step("nails availability", out,
                    not has_massage,
                    f"Should NOT show massage therapists for nails. Found massage names: {has_massage}")
        return r

    async def test_vat_not_shown(self) -> TestResult:
        """VAT calculation should never be shown to client."""
        r = TestResult("VAT — Never Show Calculation")
        ctx = self._new_context()

        out = await self._send("Body massage 60 min, how much with bank transfer?", ctx)
        has_calc = "367" in out or "= " in out or "17.5" in out
        r.add_step("bank transfer price", out,
                    not has_calc and "350" in out,
                    "Should show 350 AED, NOT 367.50 or VAT calculation")
        return r

    async def test_couple_massage(self) -> TestResult:
        """Couple massage inquiry."""
        r = TestResult("Couple Massage — Price")
        ctx = self._new_context()

        out = await self._send("Do you have couple massage?", ctx)
        r.add_step("couple massage", out,
                    "650" in out or "couple" in out.lower(),
                    "Should mention couple massage (650 AED)")
        return r

    async def test_oil_question(self) -> TestResult:
        """Client asks about oil — short answer."""
        r = TestResult("Oil Question — Short Answer")
        ctx = self._new_context()

        out = await self._send("What oil do you use for massage?", ctx)
        r.add_step("oil question", out,
                    "hypoallergenic" in out.lower() or "professional" in out.lower(),
                    "Should say 'professional hypoallergenic oils'")
        return r

    async def test_working_hours(self) -> TestResult:
        """Should know working hours."""
        r = TestResult("Working Hours — 9am to 10pm")
        ctx = self._new_context()

        out = await self._send("What are your working hours?", ctx)
        r.add_step("working hours", out,
                    ("9" in out and "10" in out) or "9am" in out.lower() or "9:00" in out,
                    "Should mention 9am-10pm hours")
        return r

    async def test_no_bot_phrases(self) -> TestResult:
        """Should not use robotic phrases."""
        r = TestResult("No Bot Phrases — Natural Language")
        ctx = self._new_context()

        out = await self._send("Hi there!", ctx)
        bot_phrases = [
            "thank you for reaching out",
            "i'd be happy to help",
            "let me assist you",
            "is there anything else i can help",
            "i appreciate your patience",
            "that's a great choice",
        ]
        has_bot = any(phrase in out.lower() for phrase in bot_phrases)
        r.add_step("greeting", out,
                    not has_bot,
                    f"Should NOT use robotic phrases. Found bot-speak: {has_bot}")
        return r

    # ═══════════════════════════════════════

    def get_all_tests(self):
        return {
            # Core booking flow
            "body_massage": self.test_body_massage_booking,
            "face_massage": self.test_face_massage,
            "combo_body_face": self.test_combo_body_face,
            "deep_facial": self.test_deep_facial_cleansing,
            "trial_session": self.test_trial_session,
            "cupping": self.test_cupping_distinction,
            "manicure": self.test_manicure,
            "pmu": self.test_pmu,
            "couple_massage": self.test_couple_massage,
            # Client behavior
            "pay_shortcut": self.test_pay_shortcut,
            "client_changes_mind": self.test_client_changes_mind,
            "next_week": self.test_next_week,
            "send_from_ad": self.test_send_from_ad,
            "discount": self.test_discount_request,
            "medical_info": self.test_medical_info,
            "oil_question": self.test_oil_question,
            # Rules & policies
            "lash_extensions": self.test_lash_extensions,
            "english_only": self.test_english_only,
            "arabic": self.test_arabic_response,
            "man_rejection": self.test_man_rejection,
            "vat_not_shown": self.test_vat_not_shown,
            "working_hours": self.test_working_hours,
            "no_bot_phrases": self.test_no_bot_phrases,
            # Technical
            "no_fake_therapists": self.test_no_fake_therapists,
            "nails_specialist": self.test_nails_specialist_only,
            "yclients_api": self.test_yclients_api,
        }


async def main():
    tester = TestAgent()
    all_tests = tester.get_all_tests()

    if len(sys.argv) > 1:
        if sys.argv[1] == "--list":
            print("Available tests:")
            for name in all_tests:
                print(f"  • {name}")
            return
        # Run specific test
        test_name = sys.argv[1]
        if test_name not in all_tests:
            print(f"Unknown test: {test_name}. Use --list to see available tests.")
            return
        tests_to_run = {test_name: all_tests[test_name]}
    else:
        tests_to_run = all_tests

    print(f"🧪 Running {len(tests_to_run)} tests...\n")

    results = []
    for name, test_fn in tests_to_run.items():
        print(f"  Running: {name}...", end=" ", flush=True)
        try:
            result = await test_fn()
            results.append(result)
            print("✅" if result.passed else "❌")
        except Exception as e:
            r = TestResult(name)
            r.add_step("(setup)", str(e), False, f"Exception: {e}")
            results.append(r)
            print(f"💥 {e}")

    await tester.yclients.close()

    # Summary
    print("\n" + "=" * 60)
    print("📊 TEST RESULTS")
    print("=" * 60)

    passed = sum(1 for r in results if r.passed)
    total = len(results)

    for r in results:
        print(r.summary())

    print(f"\n{'=' * 60}")
    print(f"{'✅' if passed == total else '⚠️'} {passed}/{total} tests passed")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
