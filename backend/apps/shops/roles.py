class Cap:
    VIEW_SHOP = "view_shop"
    MANAGE_SHOP = "manage_shop"
    MANAGE_MEMBERS = "manage_members"
    VIEW_PRODUCTS = "view_products"
    MANAGE_PRODUCTS = "manage_products"
    VIEW_COST = "view_cost"
    SELL = "sell"
    VIEW_SALES = "view_sales"
    REFUND = "refund"
    VIEW_CUSTOMERS = "view_customers"
    MANAGE_CUSTOMERS = "manage_customers"
    VIEW_REPORTS = "view_reports"


ALL_CAPS = {v for k, v in vars(Cap).items() if not k.startswith("_")}

ROLE_CAPS = {
    "owner": set(ALL_CAPS),
    "manager": ALL_CAPS - {Cap.MANAGE_MEMBERS},
    "cashier": {Cap.VIEW_SHOP, Cap.VIEW_PRODUCTS, Cap.SELL, Cap.VIEW_SALES, Cap.VIEW_CUSTOMERS, Cap.MANAGE_CUSTOMERS},
    "inventory": {Cap.VIEW_SHOP, Cap.VIEW_PRODUCTS, Cap.MANAGE_PRODUCTS, Cap.VIEW_COST},
    "accounts": {Cap.VIEW_SHOP, Cap.VIEW_PRODUCTS, Cap.VIEW_COST, Cap.VIEW_SALES, Cap.VIEW_CUSTOMERS,
                 Cap.MANAGE_CUSTOMERS, Cap.VIEW_REPORTS},
}
