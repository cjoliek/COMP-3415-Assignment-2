"""Operations used by the command-line order desk."""

from supplydesk.storage import JsonStore

CUSTOMER_TYPES = ("regular", "student")
FULFILLMENT_OPTIONS = ("pickup", "delivery")
MIN_QUANTITY = 1
MAX_QUANTITY = 99
STUDENT_DISCOUNT_PERCENT = 10
STUDENT_DISCOUNT_THRESHOLD_CENTS = 5000
DELIVERY_CHARGE_CENTS = 600
FREE_DELIVERY_THRESHOLD_CENTS = 10000
ORDER_ID_PREFIX = "ORD-"
ORDER_NUMBER_DIGITS = 4


class OrderService:
    def __init__(self, state_path=".supplydesk/state.json"):
        self.store = JsonStore(state_path)

    def catalog(self):
        return self.store.load()["catalog"]

    def quote(self, customer_type, items, fulfillment="pickup"):
        state = self.store.load()
        return self._build_quote(state, customer_type, items,fulfillment)

    def place_order(self, customer_type, items, fulfillment="pickup"):
        state = self.store.load()
        quote = self._build_quote(state, customer_type, items, fulfillment)
        order = {
            "order_id": ORDER_ID_PREFIX + str(state["next_order_number"]).zfill(ORDER_NUMBER_DIGITS),
            "status": "placed",
            **quote,
        }
        self._adjust_stock(state["catalog"], order["items"], -1)
        state["next_order_number"] += 1
        state["orders"].append(order)
        self.store.save(state)
        return order


    def list_orders(self):
        return self.store.load()["orders"]


    def get_order(self, order_id):
        return self._find_order(self.store.load(), order_id)
        

    def cancel_order(self, order_id):
        state = self.store.load()
        order = self._find_order(state, order_id)
        self._adjust_stock(state["catalog"], order["items"], +1)
        order["status"] = "cancelled"
        self.store.save(state)
        return order
    
       
    def _build_quote(self, state, customer_type, items, fulfillment):
        self._validate_request_shape(customer_type, items,fulfillment)
        lines = [self._build_line(state["catalog"], item) for item in items]
        subtotal = sum(line["line_total_cents"] for line in lines)
        discount = self._student_discount(customer_type, subtotal)
        delivery = self._delivery_charge(fulfillment, subtotal - discount)
        return {
            "customer_type": customer_type,
            "fulfillment": fulfillment,
            "items": lines,
            "subtotal_cents": subtotal,
            "discount_cents": discount,
            "delivery_cents": delivery,
            "total_cents": subtotal - discount + delivery,
        }


    @staticmethod
    def _validate_request_shape(customer_type, items, fulfillment):
        if customer_type not in CUSTOMER_TYPES:
            raise ValueError("Customer type must be regular or student.")
        if fulfillment not in FULFILLMENT_OPTIONS:
            raise ValueError ("Fulfillment must be pickup or delivery.")
        if not isinstance(items, list) or not items:
            raise ValueError("An order must contain at least one item.")


    def _build_line(self, catalog,item):
        if not isinstance(item, dict):
            raise ValueError("Each item must contain a product_id and quantity.")
        product = self._find_product(catalog, item.get("product_id"))
        if product is None:
            raise ValueError("Unknown product.")
        quantity = item.get ("quantity")
        if type(quantity) is not int or quantity < MIN_QUANTITY or quantity > MAX_QUANTITY:
            raise ValueError("Quantity must be an integer from 1 to 99.")
        if quantity > product["stock"]:
            raise ValueError("Not enough stock for " + product["product_id"] + ".")
        return{
            "product_id": product["product_id"],
            "name": product["name"],
            "unit_price_cents": product["unit_price_cents"],
            "quantity": quantity,
            "line_total_cents": product["unit_price_cents"] * quantity,   
        }

    @staticmethod
    def _student_discount(customer_type, subtotal):
        if customer_type == "student" and subtotal >= STUDENT_DISCOUNT_THRESHOLD_CENTS:
            return (subtotal * STUDENT_DISCOUNT_PERCENT + 50) // 100
        return 0


    @staticmethod
    def _delivery_charge(fulfillment, discounted_subtotal):
        if fulfillment == "delivery" and discounted_subtotal < FREE_DELIVERY_THRESHOLD_CENTS:
            return DELIVERY_CHARGE_CENTS
        return 0


    @staticmethod
    def _find_product(catalog, product_id):
        for product in catalog:
            if product["product_id"] == product_id:
                return product
        return None


    @staticmethod
    def _find_order(state, order_id):
        for order in state["orders"]:
            if order["order_id"] == order_id:
                return order
        raise ValueError("Unknown order: " + order_id)


    def _adjust_stock(self, catalog, lines, direction):
        for line in lines:
            product = self._find_product(catalog, line["product_id"])
            if product is not None:
                product["stock"] += direction * line["quantity"]