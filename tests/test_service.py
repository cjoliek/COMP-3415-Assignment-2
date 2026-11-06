import json 
from pathlib import Path 
import tempfile
import unittest

from supplydesk.service import OrderService

def item (product_id, quantity):
    return {"product_id": product_id, "quantity": quantity}

class ServiceTestCase (unittest.TestCase):

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup (self.directory.cleanup)
        self.path = Path (self.directory.name) / "state.json"
        self.service = OrderService (self.path)

    def stock_of (self, product_id):
        for product in self.service.catalog():
            if product ["product_id"] == product_id:
                return product ["stock"]
        raise AssertionError ("missing product " + product_id)

    def write_state (self, stock_overrides=None, price_overrides=None):
        state = OrderService (Path(self.directory.name) /"unused.json").store.load()
        for product in state ["catalog"]:
            pid = product ["product_id"]
            if stock_overrides and pid in stock_overrides:
                product ["stock"] = stock_overrides [pid]
            if price_overrides and pid in price_overrides:
                product ["unit_price_cents"] = price_overrides[pid]
        self.service.store.save(state)

    def file_bytes (self):
        return self.path.read_bytes() if self.path.exists() else None

#Normal behaviour

class NormalBehaviourTests (ServiceTestCase):
    def test_new_save_file_starts_with_spec_catalog (self):
        expected = {
            "notebook": ("Notebook", 500, 20),
            "pen-pack": ("Pen pack", 750, 10),
            "hoodie": ("Campus hoodie", 4000, 5),
            "mug": ("Campus mug",1500, 8),
            "bag": ("Canvas bag", 2500, 4),
        }
        actual = {p["product_id"]: (p["name"], p["unit_price_cents"], p["stock"])
                  for p in self.service.catalog()}
        self.assertEqual (actual, expected)

    def test_quote_contains_all_required_fields (self):
        quote = self.service.quote ("student", [item ("mug", 2), item ("notebook", 1)], "delivery")
        self.assertEqual (quote ["customer_type"], "student")
        self.assertEqual (quote ["fulfillment"], "delivery")
        self.assertEqual (quote ["items"], [
            {"product_id": "mug", "name": "Campus mug", "unit_price_cents": 1500,
            "quantity": 2, "line_total_cents": 3000},
            {"product_id": "notebook", "name": "Notebook", "unit_price_cents": 500,
            "quantity": 1, "line_total_cents": 500}
        ])
        self.assertEqual (quote ["subtotal_cents"], 3500)
        self.assertEqual (quote ["discount_cents"], 0)
        self.assertEqual (quote ["delivery_cents"], 600)
        self.assertEqual (quote ["total_cents"], 4100)
        self.assertNotIn ("order_id", quote)
        self.assertNotIn ("status", quote)

    def test_spec_example_regular_delivery_three_hoodies (self):
        quote = self.service.quote ("regular", [item("hoodie", 3)], "delivery")
        self.assertEqual ((quote ["subtotal_cents"], quote["discount_cents"],
                           quote ["delivery_cents"], quote ["total_cents"]),
                           (12000, 0, 0, 12000))

    def test_student_discount_applies_above_threshold (self):
        quote = self.service.quote ("student", [item("bag", 2), item("notebook", 1)])
        self.assertEqual (quote["subtotal_cents"], 5500)
        self.assertEqual (quote["discount_cents"], 550)
        self.assertEqual (quote["total_cents"], 4950)

    def test_place_order_deducts_stock_and_saves(self):
        order = self.service.place_order ("regular", [item ("bag", 1), item ("pen-pack", 3)])
        self.assertEqual (order ["order_id"], "ORD-0001")
        self.assertEqual (order ["status"], "placed")
        self.assertEqual (self.stock_of ("bag"), 3)
        self.assertEqual (self.stock_of ("pen-pack"), 7)
        reopened = OrderService (self.path)
        self.assertEqual (reopened.list_orders (), [order])

    def test_cancel_restores_stock_and_keeps_order_in_history (self):
        order = self.service.place_order ("student", [item("hoodie", 2)], "delivery")
        cancelled = self.service.cancel_order (order ["order_id"])
        self.assertEqual (cancelled ["status"], "cancelled")
        self.assertEqual (self.stock_of ("hoodie"), 5)
        history = self.service.list_orders ()
        self.assertEqual (len(history), 1)
        expected = dict (order, status = "cancelled")
        self.assertEqual (history [0], expected)

#Boundary behaviour

class BoundaryBehaviourTests (ServiceTestCase):
    def test_quantity_one_is_accepted (self):
        quote = self.service.quote ("regular", [item("notebook", 1)])
        self.assertEqual (quote ["total_cents"], 500)

    def test_quantity_99_is_accepted_when_stock_allows (self):
        self.write_state (stock_overrides={"notebook": 200})
        quote = self.service.quote ("regular", [item("notebook", 99)])
        self.assertEqual (quote ["subtotal_cents"], 49500)

    def test_quantity_zero_is_rejected (self):
        with self.assertRaises (ValueError):
            self.service.quote ("regular", [item("notebook", 0)])
    
    def test_quantity_100_is_rejected_even_with_enough_stock (self):
        self.write_state (stock_overrides={"notebook": 200})
        with self.assertRaises (ValueError):
            self.service.quote ("regular", [item ("notebook", 100)])

    def test_ordering_exactly_all_stock_is_allowed (self):
        order = self.service.place_order ("regular", [item ("hoodie", 5)])
        self.assertEqual (order ["items"][0]["quantity"], 5)
        self.assertEqual (self.stock_of ("hoodie"), 0)

    def test_one_more_than_stock_is_rejected (self):
        with self.assertRaises (ValueError):
            self.service.quote ("regular", [item ("hoodie", 6)])

    def test_student_discount_at_exactly_5000_cents (self):
        quote = self.service.quote ("student", [item ("bag", 2)])
        self.assertEqual (quote ["subtotal_cents"], 5000)
        self.assertEqual (quote ["discount_cents"], 500)
        self.assertEqual (quote ["total_cents"], 4500)

    def test_student_just_below_discount_threshold (self):
        quote = self.service.quote ("student", [item ("notebook", 8), item ("pen-pack", 1)])
        self.assertEqual (quote ["subtotal_cents"], 4750)
        self.assertEqual (quote ["discount_cents"], 0)

    def test_delivery_free_at_exactly_10000_after_discount (self):
        quote = self.service.quote ("regular", [item ("bag", 4)], "delivery")
        self.assertEqual (quote ["subtotal_cents"], 10000)
        self.assertEqual (quote ["delivery_cents"], 0)
        self.assertEqual (quote ["total_cents"], 10000)

    def test_delivery_threshold_uses_discounted_amount (self):
        quote = self.service.quote ("student", [item ("hoodie", 2), item ("mug", 2)], "delivery")
        self.assertEqual (quote ["subtotal_cents"], 11000)
        self.assertEqual (quote ["discount_cents"], 1100)
        self.assertEqual (quote ["delivery_cents"], 600)
        self.assertEqual (quote ["total_cents"], 10500)

    def test_discount_rounds_half_cent_upward(self):
        self.write_state (price_overrides={"notebook": 5005})
        quote = self.service.quote ("student", [item ("notebook", 1)])
        self.assertEqual (quote ["discount_cents"], 501)
        self.assertEqual (quote ["total_cents"], 4504)

    def test_combined_duplicate_lines_may_not_exceed_stock(self):
        with self.assertRaises (ValueError):
            self.service.place_order ("regular", [item ("hoodie", 3), item ("hoodie", 3)])
        self.assertEqual (self.stock_of ("hoodie"), 5)
        self.assertFalse (self.path.exists())

    def test_duplicate_lines_within_stock_remain_separate (self):
        quote = self.service.quote ("regular", [item ("hoodie", 2), item ("hoodie", 3)])
        self.assertEqual ([line["quantity"] for line in quote ["items"]], [2, 3])
        self.assertEqual (quote ["subtotal_cents"], 20000)

#Invalid or exceptional behaviour

class InvalidBehaviourTests (ServiceTestCase):
    INVALID_REQUESTS = [
        ("customer type", ("Student", [item ("mug", 1)], "pickup")),
        ("customer type None", (None, [item ("mug", 1)], "pickup")),
        ("fulfillment", ("regular", [item ("mug", 1)], "shipping")),
        ("empty items", ("regular", [], "pickup")),
        ("items not a list", ("regular", item ("mug", 1), "pickup")),
        ("items not a dict", ("regular", ["mug"], "pickup")),
        ("unknown product", ("regular", [item ("laptop", 1)], "pickup")),
        ("missing quantity", ("regular", [{"product_id": "mug"}], "pickup")),
        ("boolean quantity", ("regular", [item ("mug", True)], "pickup")),
        ("float quantity", ("regular", [item ("mug", 2.0)], "pickup")),
        ("string quantity", ("regular", [item ("mug", "2")], "pickup")),
        ("negative quantity", ("regular", [item ("mug", -1)], "pickup")),
        ("one bad line among good", ("regular", [item ("mug", 1), item ("laptop", 1)], "pickup")),
    ]

    def test_invalid_quotes_raise_value_error (self):
        for label, args in self.INVALID_REQUESTS:
            with self.subTest (label):
                with self.assertRaises (ValueError):
                    self.service.quote (*args)

    def test_invalid_placement_leaves_saved_data_unchanged(self):
        first =self.service.place_order ("regular", [item ("mug", 1)])
        before = self.file_bytes ()
        for label, args in self.INVALID_REQUESTS:
            with self.subTest (label):
                with self.assertRaises (ValueError):
                    self.service.place_order (*args)
                self.assertEqual(self.file_bytes(), before)
        second = self.service.place_order ("regular", [item("mug", 1)])
        self.assertEqual ((first ["order_id"], second ["order_id"]), ("ORD-0001", "ORD-0002"))

    def test_invalid_placement_on_new_file_creates_nothing (self):
        with self.assertRaises (ValueError):
            self.service.place_order ("regular", [item ("bag", 5)])
        self.assertFalse (self.path.exists())

    def test_get_unknown_order_raises (self):
        with self.assertRaises (ValueError):
            self.service.get_order ("ORD-9999")

    def test_cancel_unknown_order_raises_without_saving(self):
        self.service.place_order ("regular", [item ("mug", 1)])
        before = self.file_bytes ()
        with self.assertRaises (ValueError):
            self.service.cancel_order ("ORD-9999")
        self.assertEqual (self.file_bytes(), before)

    def test_malformed_save_file_raises_instead_of_resetting (self):
        self.path.write_text ("{ not valid json", encoding= "utf-8")
        with self.assertRaises (ValueError):
            self.service.catalog ()
        self.assertEqual (self.path.read_text (encoding="utf-8"), "{ not valid json")

    def test_cancelling_twice_does_not_restore_stock_twice (self):
        order = self.service.place_order ("regular", [item ("bag", 2)])
        self.service.cancel_order (order ["order_id"])
        after_first = self.file_bytes ()
        again = self.service.cancel_order (order ["order_id"])
        self.assertEqual (again ["status"], "cancelled")
        self.assertEqual (self.stock_of ("bag"), 4)
        self.assertEqual (self.file_bytes(), after_first)

# Behaviour important to preserve during refactoring

class PreservedBehaviourTests (ServiceTestCase):
    REQUESTS = [
        ("regular", [item ("notebook", 2)], "pickup"),
        ("student", [item ("hoodie", 2)], "delivery"),
        ("regular", [item ("hoodie", 3)], "delivery"),
        ("student", [item ("bag", 1), item ("mug", 2), item ("pen-pack", 1)], "delivery"),
        ("student", [item ("notebook", 3), item ("notebook", 4)], "pickup"),
    ]

    def test_placed_order_matches_preceding_quote (self):
        for customer, items, fulfillment in self.REQUESTS:
            with self.subTest (customer= customer, items= items,fulfillment= fulfillment):
                service = OrderService (Path (self.directory.name) / (customer + fulfillment + str(len(items))))
                quote = service.quote (customer, items, fulfillment)
                order = service.place_order (customer, items, fulfillment)
                stripped = {k: v for k, v in order.items () if k not in ("order_id", "status")}
                self.assertEqual (stripped, quote)

    def test_quote_does_not_create_file_or_change_stock (self):
        before = self.service.catalog ()
        self.service.quote ("regular", [item ("bag", 4)], "delivery")
        self.assertFalse (self.path.exists ())
        self.service.place_order ("regular", [item ("mug", 1)])
        saved = self.file_bytes ()
        self.service.quote ("student", [item ("hoodie", 5)])
        self.assertEqual (self.file_bytes(), saved)
        self.assertEqual (self.stock_of ("hoodie"), 5)
        self.assertEqual (len (before), 5)

    def test_quote_rechecks_stock_after_placement (self):
        self.service.place_order ("regular", [item ("bag", 3)])
        with self.assertRaises (ValueError):
            self.service.quote ("regular", [item ("bag", 2)])

    def test_order_ids_are_sequential_and_never_reused (self):
        ids = [self.service.place_order ("regular", [item ("notebook", 1)]) ["order_id"]
                for _ in range (3)]
        self.service.cancel_order ("ORD-0002")
        ids.append (self.service.place_order ("regular", [item ("notebook", 1)]) ["order_id"])
        self.assertEqual (ids, ["ORD-0001", "ORD-0002", "ORD-0003", "ORD-0004"])

    def test_history_keeps_placement_order_including_cancelled (self):
        self.service.place_order ("regular", [item ("mug", 1)])
        self.service.place_order ("student", [item ("bag", 1)])
        self.service.cancel_order ("ORD-0001")
        history = OrderService (self.path).list_orders ()
        self.assertEqual ([(o["order_id"], o["status"]) for o in history],
                          [("ORD-0001", "cancelled"), ("ORD-0002", "placed")])

    def test_historical_prices_not_recalculated_after_catalog_change (self):
        order = self.service.place_order ("regular", [item ("mug", 2)])
        state = json.loads (self.path.read_text (encoding= "utf-8"))
        for product in state ["catalog"]:
            if product ["product_id"] == "mug":
                product ["unit_price_cents"] = 9999
        self.path.write_text(json.dumps (state), encoding="utf-8")
        reopened = OrderService (self.path)
        self.assertEqual (reopened.get_order (order ["order_id"]) ["total_cents"], 3000)
        self.assertEqual (reopened.cancel_order (order ["order_id"]) ["total_cents"], 3000)

    def test_saved_file_uses_schema_version_1 (self):
        self.service.place_order ("regular", [item ("mug", 1)])
        state = json.loads (self.path.read_text (encoding= "utf-8"))
        self.assertEqual (state["schema_version"], 1)
        self.assertEqual (state ["next_order_number"], 2)

if __name__ == "__main__":
    unittest.main()
