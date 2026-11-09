import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from supplydesk.cli import main
from supplydesk.menu import run_menu
from supplydesk.service import OrderService


def item (product_id, quantity):
    return {"product_id": product_id, "quantity": quantity}


def money_fields(result):
    return (result["subtotal_cents"], result["discount_cents"],
            result["delivery_cents"], result["total_cents"])


class ExpressServiceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "state.json"
        self.service = OrderService(self.path)

    def stock_of(self, product_id):
        for product in self.service.catalog():
            if product["product_id"] == product_id:
                return product["stock"]
        raise AssertionError("missing product " +product_id)

    def test_CR_01_example_regular_two_notebooks_express(self):
        quote = self.service.quote("regular", [item("notebook", 2)], "express")
        self.assertEqual(money_fields(quote), (1000, 0, 1200, 2200))


    def test_CR_01_example_student_two_hoodies_express(self):
        quote = self.service.quote("student", [item("hoodie", 2)], "express")
        self.assertEqual(money_fields(quote), (8000, 800, 1200, 8400))    


    def test_CR_01_example_three_hoodies_standard_vs_express(self):
        standard = self.service.quote("regular", [item("hoodie", 3)], "delivery")
        express = self.service.quote("regular", [item("hoodie", 3)], "express")
        self.assertEqual(standard["total_cents"], 12000)
        self.assertEqual(express["total_cents"], 13200)


    def test_express_fee_not_waived_at_free_delivery_threshold(self):
        quote = self.service.quote("regular", [item("bag", 4)], "express")
        self.assertEqual(quote["subtotal_cents"], 10000)
        self.assertEqual(quote["delivery_cents"], 1200)
        self.assertEqual(quote["total_cents"], 11200)


    def test_student_discount_boundary_unchanged_with_express(self):
        quote = self.service.quote("student", [item("bag", 2)], "express")
        self.assertEqual(money_fields(quote), (5000, 500, 1200, 5700))


    def test_express_fee_does_not_make_student_eligible_for_discount(self):
        quote = self.service.quote("student", [item("mug", 3)], "express")
        self.assertEqual(money_fields(quote), (4500, 0, 1200, 5700))


    def test_pickup_and_standard_delivery_unchanged(self):
        self.assertEqual(self.service.quote("regular", [item("notebook", 2)])["delivery_cents"], 0)
        self.assertEqual(self.service.quote("regular", [item("notebook", 2)], "delivery")["delivery_cents"], 600)
        self.assertEqual(self.service.quote("regular", [item("bag", 4)], "delivery")["delivery_cents"], 0)


    def test_express_order_matches_quote(self):
        quote = self.service.quote("student", [item("hoodie", 2), item ("mug", 1)], "express")
        order = self.service.place_order("student", [item("hoodie", 2), item ("mug", 1)], "express")
        stripped = {k: v for k,v in order.items() if k not in("order_id", "status")}
        self.assertEqual(stripped, quote)


    def test_express_order_kept_after_reopen_and_cancel(self):
        order = self.service.place_order("student", [item("hoodie", 2)], "express")
        reopened = OrderService(self.path)
        self.assertEqual(reopened.get_order(order["order_id"]), order)
        cancelled = reopened.cancel_order(order["order_id"])
        self.assertEqual(cancelled["status"], "cancelled")
        self.assertEqual(cancelled["fulfillment"], "express")
        self.assertEqual(money_fields(cancelled), (8000, 800, 1200, 8400))
        self.assertEqual(cancelled["items"], order["items"])
        self.assertEqual(self.stock_of("hoodie"), 5)


    def test_express_order_deducts_stock_and_numbers_sequentially(self):
        first = self.service.place_order("regular", [item("bag", 1)], "express")
        second = self.service.place_order("regular", [item("bag", 1)], "pickup")
        self.assertEqual((first["order_id"], second["order_id"]), ("ORD-0001", "ORD-0002"))
        self.assertEqual(self.stock_of("bag"), 2)

    def test_express_still_checks_stock(self):
        with self.assertRaises(ValueError):
            self.service.place_order("regular", [item("bag", 5)], "express")
        self.assertFalse(self.path.exists())


    def test_other_fulfillment_values_remain_invalid(self):
        for value in ("Express", "EXPRESS", "express ", "overnight", "", None):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    self.service.quote("regular", [item("mug", 1)], value)


    def test_default_fulfillment_is_still_pickup(self):
        self.assertEqual(self.service.quote("regular", [item("mug", 1)])["fulfillment"], "pickup")


class ExpressInterfaceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "state.json"


    def run_cli(self,*args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                status = main(["--data", str(self.path), *args])
            except SystemExit as exit_:
                status = exit_.code
        return status, out.getvalue(), err.getvalue()


    def run_menu_With(self, *lines):
        out= io.StringIO()
        prompts = []

        def fake_input(prompt=""):
            prompts.append(prompt)
            if not script:
                raise EOFError
            return script.pop(0)

        script = list(lines)
        with mock.patch("builtins.input", side_effect=fake_input), contextlib.redirect_stdout(out):
            run_menu(OrderService(self.path))
        return out.getvalue(), prompts


    def test_cli_quote_express_example(self):
        status, out, _ = self.run_cli("quote", "--customer", "student",
                                      "--fulfillment", "express", "--item", "hoodie:2")
        self.assertEqual(status, 0)
        self.assertEqual(json.loads(out)["total_cents"], 8400)

    
    def test_cli_place_express_saves_fulfillment(self):
        status, out, _ = self.run_cli("place", "--fulfillment", "express", "--item", "mug:1")
        self.assertEqual(status, 0)
        self.assertEqual(json.loads(out)["fulfillment"], "express")
        _, out, _ = self.run_cli("show", "ORD-0001")
        self.assertEqual(json.loads(out)["delivery_cents"], 1200)


    def test_cli_rejects_unknown_fulfillment(self):
        status, _, _ = self.run_cli("quote", "--fulfillment", "overnight", "--item", "mug:1")
        self.assertEqual(status, 2)


    def test_cli_help_list_express(self):
        status, out, _ = self.run_cli("quote", "--help")
        self.assertEqual(status, 0)
        self.assertIn("express", out)


    def test_menu_quote_express(self):
        out, prompts = self.run_menu_With("2", "student", "hoodie", "2", "", "express", "0")
        self.assertIn("Total: $84.00", out)
        self.assertIn("Delivery: $12.00", out)
        fulfillment_prompts = [p for p in prompts if p.startswith("Fulfillment")]
        self.assertTrue(fulfillment_prompts)
        self.assertIn("express", fulfillment_prompts[0])

    def test_menu_fulfillment_still_defaults_to_pickup(self):
        out, _ = self.run_menu_With("2", "", "mug", "1", "", "", "0")
        self.assertIn("Fulfillment: pickup", out)
        self.assertIn("Total: $15.00", out)


if __name__ == "__main__":
    unittest.main()