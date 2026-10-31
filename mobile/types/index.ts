export type Shop = { id: number; name: string; role: string; approved: boolean; capabilities: string[] };
export type Session = { token: string; user: { id: number; username: string; full_name: string; email: string; must_change_password: boolean }; shops: Shop[] };
export type Master = {
  id: number; display_name: string; name: string; brand_name: string; mrp: string | null;
  tax_rate: string | null; barcodes: string[]; my_listing_id: number | null; 
  unit: string; is_loose: boolean; category?: number | null; category_name?: string;
};
export type ShopProduct = {
  id: number; master_product: Master; selling_price: string; purchase_cost?: string;
  stock_qty: string; low_stock_threshold: string; is_enabled: boolean; is_low_stock: boolean; master_active: boolean;
  expiry_date: string | null; days_to_expiry: number | null; expiry_status: "expired" | "expiring_soon" | "ok" | null;
  online_visible?: boolean;
};

export type Customer = { id: number; name: string; phone: string; whatsapp_number: string; balance: string; credit_limit: string | null };
export type Page<T> = { count: number; results: T[] };
