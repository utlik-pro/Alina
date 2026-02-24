"""
Generate test scenarios from parsed client chats.
Creates realistic dialog sequences for testing the AI agent.

Usage: python3 scripts/generate_test_scenarios.py
Input:  scripts/output/chat_analysis.json
Output: scripts/output/test_scenarios.json
"""

import json
import os
import re
from typing import Dict, List


def extract_booking_flows(analysis: Dict) -> List[Dict]:
    """Extract complete booking flow examples from analyzed dialogs."""
    scenarios = []

    for dialog in analysis["dialogs"]:
        cls = dialog["classification"]
        name = dialog["client_name"]

        # Get messages from start and end samples
        start_msgs = dialog.get("sample_start", [])
        end_msgs = dialog.get("sample_end", [])

        # Build a basic scenario from each dialog
        scenario = {
            "name": f"Real dialog: {name}",
            "source": dialog["source_file"],
            "outcome": cls["outcome"],
            "services": cls["services"],
            "payment": cls.get("payment_method", "unknown"),
            "total_messages": cls["total_messages"],
            "multi_msg_sequences": cls.get("multi_message_sequences", 0),
            "start_sample": [
                {"role": "staff" if m["is_staff"] else "client", "text": m["text"][:200]}
                for m in start_msgs if m["text"].strip()
            ],
            "end_sample": [
                {"role": "staff" if m["is_staff"] else "client", "text": m["text"][:200]}
                for m in end_msgs if m["text"].strip()
            ],
        }
        scenarios.append(scenario)

    return scenarios


def create_synthetic_scenarios() -> List[Dict]:
    """Create synthetic test scenarios based on common patterns."""
    return [
        {
            "id": "new_client_body_massage",
            "name": "New client from ad: body massage",
            "description": "Client comes from Instagram ad asking about body massage",
            "messages": [
                {"role": "client", "text": "Hello"},
                {"role": "client", "text": "I saw your ad on Instagram"},
                {"role": "client", "text": "How much for body massage?"},
                # Agent should respond with prices: 60 min 350 AED, 90 min 480 AED
                {"role": "client", "text": "60 min please"},
                {"role": "client", "text": "Tomorrow at 3 pm"},
                # Agent should ask for location
                {"role": "client", "text": "[Location shared]"},
                {"role": "client", "text": "Villa 45"},
                {"role": "client", "text": "Sara"},
                {"role": "client", "text": "Cash"},
            ],
            "expected_outcome": "booking_confirmed",
            "expected_service": "Body massage 60 min",
            "expected_price": 350,
        },
        {
            "id": "body_face_combo",
            "name": "Client asking about body + face combo",
            "messages": [
                {"role": "client", "text": "Hi, I want body and face massage"},
                # Agent should offer combo: 85 min 650 AED
                {"role": "client", "text": "Yes that sounds good"},
                {"role": "client", "text": "Do you have tomorrow evening?"},
                {"role": "client", "text": "7:30 pm"},
            ],
            "expected_outcome": "booking_in_progress",
            "expected_service": "Body + Face massage",
            "expected_price": 650,
        },
        {
            "id": "price_objection",
            "name": "Client says too expensive",
            "messages": [
                {"role": "client", "text": "Hello"},
                {"role": "client", "text": "I want body massage"},
                {"role": "client", "text": "That's too expensive"},
                # Agent should handle objection with medical education script
            ],
            "expected_outcome": "objection_handling",
            "expected_response_contains": ["medical education", "certified", "qualified"],
        },
        {
            "id": "male_client",
            "name": "Male client inquiry",
            "messages": [
                {"role": "client", "text": "Hi, I want to book massage"},
                {"role": "client", "text": "My name is Ahmed"},
            ],
            "expected_outcome": "gender_policy_applied",
            "expected_response_contains": ["women only", "ladies only"],
        },
        {
            "id": "multi_message_rapid",
            "name": "Client sends 4 rapid messages (buffering test)",
            "description": "Tests that buffer collects all messages before processing",
            "messages": [
                {"role": "client", "text": "Hi", "delay_sec": 0},
                {"role": "client", "text": "I need body massage", "delay_sec": 2},
                {"role": "client", "text": "60 min", "delay_sec": 3},
                {"role": "client", "text": "Tomorrow", "delay_sec": 5},
            ],
            "expected_outcome": "single_combined_response",
            "buffer_test": True,
        },
        {
            "id": "lashes_extension",
            "name": "Client asks about eyelash extensions",
            "messages": [
                {"role": "client", "text": "Hello, how much for lashes?"},
                # Agent should offer: Classical 300, 2D 350, Russian 400
                {"role": "client", "text": "What's the difference?"},
                {"role": "client", "text": "I'll take 2D volume"},
            ],
            "expected_outcome": "booking_in_progress",
            "expected_service": "Eyelash extension 2D volume",
            "expected_price": 350,
        },
        {
            "id": "combo_mani_pedi",
            "name": "Client asks about nails",
            "messages": [
                {"role": "client", "text": "Do you do nails?"},
                # Agent should offer manicure + pedicure options
                {"role": "client", "text": "Manicure and pedicure please"},
                {"role": "client", "text": "Russian gelish"},
            ],
            "expected_outcome": "booking_in_progress",
            "expected_service": "Combo mani + pedi",
            "expected_price": 380,
        },
        {
            "id": "payment_vat_question",
            "name": "Client asks about payment and VAT",
            "messages": [
                {"role": "client", "text": "How can I pay?"},
                # Agent should explain: Cash tax-free, Transfer +5% VAT
                {"role": "client", "text": "Can I pay by bank transfer?"},
            ],
            "expected_outcome": "vat_explained",
            "expected_response_contains": ["cash", "tax free", "5%", "VAT"],
        },
        {
            "id": "location_question",
            "name": "Client asks where they are located",
            "messages": [
                {"role": "client", "text": "Where are you located?"},
            ],
            "expected_outcome": "location_explained",
            "expected_response_contains": ["home service", "your location", "Abu Dhabi", "Al Ain"],
        },
        {
            "id": "permanent_makeup",
            "name": "Client asks about permanent makeup",
            "messages": [
                {"role": "client", "text": "Do you do permanent makeup?"},
                {"role": "client", "text": "How much for lips?"},
            ],
            "expected_outcome": "booking_in_progress",
            "expected_service": "Permanent makeup lips",
            "expected_price": 1200,
        },
        {
            "id": "deep_cleansing_ramadan",
            "name": "Client asks about Ramadan promo",
            "messages": [
                {"role": "client", "text": "Hi, do you have any offers?"},
                # Agent should mention current promotions
                {"role": "client", "text": "Tell me about the deep cleansing offer"},
            ],
            "expected_outcome": "promo_explained",
            "expected_response_contains": ["Ramadan", "Deep Cleansing", "420"],
        },
        {
            "id": "referral_program",
            "name": "Client asks about Book a Friend",
            "messages": [
                {"role": "client", "text": "I heard you have a referral program?"},
            ],
            "expected_outcome": "referral_explained",
            "expected_response_contains": ["Book a Friend", "50 AED", "coupon"],
        },
        {
            "id": "cupping_therapy",
            "name": "Client asks about cupping/hijama",
            "messages": [
                {"role": "client", "text": "Do you do cupping?"},
                {"role": "client", "text": "How much?"},
            ],
            "expected_outcome": "booking_in_progress",
            "expected_service": "Cupping therapy",
            "expected_price": 350,
        },
        {
            "id": "returning_client_package",
            "name": "Returning client asking about packages",
            "messages": [
                {"role": "client", "text": "Hi, I want to buy a package"},
                {"role": "client", "text": "Body massage package"},
            ],
            "expected_outcome": "package_offered",
            "expected_response_contains": ["package", "sessions"],
        },
        {
            "id": "service_change_mid_booking",
            "name": "Client changes service during booking",
            "messages": [
                {"role": "client", "text": "I want face massage"},
                {"role": "client", "text": "Actually, can I have body massage instead?"},
            ],
            "expected_outcome": "service_updated",
            "expected_service": "Body massage",
        },
        {
            "id": "waxing_inquiry",
            "name": "Client asks about face waxing",
            "messages": [
                {"role": "client", "text": "Do you do waxing?"},
                {"role": "client", "text": "Full face please"},
            ],
            "expected_outcome": "booking_in_progress",
            "expected_service": "Full face waxing",
            "expected_price": 100,
        },
    ]


def main():
    # Load analysis
    analysis_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "output", "chat_analysis.json"
    )
    with open(analysis_path) as f:
        analysis = json.load(f)

    # Extract real booking flows
    real_flows = extract_booking_flows(analysis)

    # Create synthetic scenarios
    synthetic = create_synthetic_scenarios()

    # Combine
    output = {
        "metadata": {
            "generated_from": "33 real Crystal Lab client chats",
            "total_real_scenarios": len(real_flows),
            "total_synthetic_scenarios": len(synthetic),
        },
        "key_insights": {
            "conversion_rate": "97% (32/33 dialogs ended in booking)",
            "top_services": analysis["services_mentioned"],
            "dominant_payment": "Cash (25/29 = 86%)",
            "avg_messages_per_dialog": analysis["summary"]["avg_messages_per_dialog"],
            "multi_message_patterns": f"{len(analysis['multi_message_patterns'])} sequences found",
            "common_client_intents": {
                intent: len(phrases)
                for intent, phrases in analysis["client_phrases_by_intent"].items()
            },
        },
        "synthetic_test_scenarios": synthetic,
        "real_dialog_summaries": real_flows,
        "client_phrases_for_training": analysis["client_phrases_by_intent"],
        "faq_for_agent": analysis["faq"],
    }

    output_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "output", "test_scenarios.json"
    )
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"Generated {len(synthetic)} synthetic test scenarios")
    print(f"Extracted {len(real_flows)} real dialog summaries")
    print(f"Saved to: {output_path}")

    # Print synthetic scenario summary
    print("\nSynthetic Test Scenarios:")
    for s in synthetic:
        price_str = f", {s.get('expected_price', '?')} AED" if s.get("expected_price") else ""
        svc = s.get("expected_service", "")
        print(f"  [{s['id']}] {s['name']} -> {s.get('expected_outcome', '?')}{price_str}")


if __name__ == "__main__":
    main()
