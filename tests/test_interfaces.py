import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock 

from supplydesk.cli import main
from supplydesk.menu import money, run_menu
from supplydesk.service import OrderService

class TempStateMixin:
    def setUp (self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup (self.directory.cleanup)
        self.path = Path (self.directory.name) / "state.json"

class CommandLineTests (TempStateMixin, unittest.TestCase):
    def run_cli (self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr (err):
            try:
                status = main (["--data", str (self.path), *args])
            except SystemExit as exit_:
                status = exit_.code
        return status, out.getvalue(), err.getvalue()

    def test_quote_uses_defaults_and_prints_json_cents (self):
        status, out, _ = self.run_cli ("quote", "--item", "notebook:2")
        self.assertEqual (status, 0)
        result = json.loads (out)
        self.assertEqual (result["customer_type"], "regular")
        self.assertEqual (result["fulfillment"], "pickup")
        self.assertEqual (result["total_cents"], 1000)
        self.assertFalse (self.path.exists())

    def test_place_show_cancel_round_trip (self):
        status, out, _ = self.run_cli ("place", "--customer", "student",
                                        "--fulfillment", "delivery", "--item", "hoodie:2")
        self.assertEqual (status, 0)
        self.assertEqual (json.loads (out) ["total_cents"], 7800)
        status, out, _ = self.run_cli ("show", "ORD-0001")
        self.assertEqual (json.loads (out) ["status"], "placed")
        status, out, _ = self.run_cli ("cancel", "ORD-0001")
        self.assertEqual (json.loads (out) ["status"], "cancelled")
        status, out, _ = self.run_cli ("orders")
        self.assertEqual ([o ["order_id"] for o in json.loads (out)], ["ORD-0001"])

    def test_rejected_service_request_exits_2 (self):
        status, out, err = self.run_cli ("place", "--item", "bag:5")
        self.assertEqual (status, 2)
        self.assertEqual (out, "")
        self.assertIn ("Error:", err)
        self.assertFalse (self.path.exists ())

    def test_non_integer_quantity_rejected_by_parser (self):
        status, _, err = self.run_cli ("quote", "--item", "notebook:two")
        self.assertEqual (status, 2)
        self.assertIn ("integer", err)

    def test_unknown_customer_rejected_by_parser (self):
        status, _, _ = self.run_cli ("quote", "--customer", "staff", "--item", "mug:1")
        self.assertEqual (status, 2)

    def test_show_unknown_order_exits_2(self):
        status, _, err = self.run_cli ("show", "ORD-0042")
        self.assertEqual (status, 2)
        self.assertIn ("Unknown order", err)

class MenuTest (TempStateMixin, unittest.TestCase):
    def run_menu_with (self, *lines):
        service = OrderService (self.path)
        out = io.StringIO()
        script = list(lines) + [EOFError ()]
        with mock.patch ("builtins.input", side_effect= script), contextlib.redirect_stdout (out):
            status = run_menu (service)
        return status, out.getvalue(),service 

    def test_money_formats_cents_as_dollars (self):
        self.assertEqual (money(0), "$0.00")
        self.assertEqual (money(5), "$0.05")
        self.assertEqual (money(7800), "$78.00")
        self.assertEqual (money(12345), "$123.45")

    def test_readme_first_quote_shows_ten_dollars (self):
        status, out, _= self.run_menu_with ("2", "", "notebook", "2", "", "", "0")
        self.assertEqual (status, 0)
        self.assertIn ("Total: $10.00", out)
        self.assertIn ("Quote only", out)
        self.assertFalse (self.path.exists())

    def test_declining_placement_leaves_no_saved_data (self):
        _, out, _ =self.run_menu_with ("3", "student", "mug", "1", "", "delivery", "n", "0")
        self.assertIn ("Order not placed.", out)
        self.assertFalse (self.path.exists ())

    def test_confirming_placement_saves_orders (self):
        _, out, service= self.run_menu_with ("3", "", "bag", "1", "", "", "y","0")
        self.assertIn ("ORD-0001 - placed", out)
        self.assertEqual (len (service.list_orders()), 1)

    def test_bad_quantity_text_asks_again (self):
        _, out, _= self.run_menu_with ("2", "", "mug", "two", "mug", "1", "", "", "0")
        self.assertIn ("Re-enter this item", out)
        self.assertIn ("Total: $15.00", out)

    def test_invalid_request_reports_error_and_returns_to_menu (self):
        _, out, _, = self.run_menu_with ("2", "", "laptop", "1", "", "", "1", "0")
        self.assertIn ("Error: Unknown product.", out)
        self.assertIn ("Goodbye.", out)

    def test_declining_cancellation_keeps_order (self):
        _, _, service = self.run_menu_with ("3", "", "mug", "1", "", "", "y", "6", "ORD-0001", "n", "0")
        self.assertEqual ((service.get_order) ("ORD-0001") ["status"], "placed")

    def test_end_of_input_exits_cleanly (self):
        status, out, _ = self.run_menu_with ()
        self.assertEqual (status, 0)
        self.assertIn ("Goodbye.", out)
if __name__ == "__main__":
    unittest.main ()