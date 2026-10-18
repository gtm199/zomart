export type Shop = { id: number; name: string; role: string; capabilities: string[] };
export type Session = { token: string; user: { id: number; username: string; full_name: string }; shops: Shop[] };
export type Master = {
  id: number; display_name: string; name: string; brand_name: string; mrp: string | null;
  tax_rate: string | null; barcodes: string[]; my_listing_id: number | null;
};
export type ShopProduct = {
  id: number; master_product: Master; selling_price: string; purchase_cost?: string;
  stock_qty: string; low_stock_threshold: string; is_enabled: boolean; is_low_stock: boolean; master_active: boolean;
  expiry_date: string | null; days_to_expiry: number | null; expiry_status: "expired" | "expiring_soon" | "ok" | null;
};

export type Customer = { id: number; name: string; phone: string; balance: string };
export type Page<T> = { count: number; results: T[] };
