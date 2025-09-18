import sqlite3
import hashlib
import binascii
import csv
import datetime
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog


import customtkinter as ctk
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import matplotlib.pyplot as plt

DB_FILE = 'inventory.db'
SALT = b'some_static_salt_change_it'


def get_conn():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def hash_password(password: str) -> str:
    dk = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), SALT, 100000)
    return binascii.hexlify(dk).decode('ascii')


def verify_password(password: str, stored_hash: str) -> bool:
    return hash_password(password) == stored_hash


def init_db():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute('''
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL
    )
    ''')
    cur.execute('''
    CREATE TABLE IF NOT EXISTS products (
        id INTEGER PRIMARY KEY,
        sku TEXT UNIQUE,
        name TEXT NOT NULL,
        description TEXT,
        price REAL NOT NULL DEFAULT 0,
        quantity INTEGER NOT NULL DEFAULT 0,
        min_quantity INTEGER NOT NULL DEFAULT 5
    )
    ''')
    cur.execute('''
    CREATE TABLE IF NOT EXISTS sales (
        id INTEGER PRIMARY KEY,
        product_id INTEGER,
        quantity INTEGER,
        total_price REAL,
        sold_at TEXT,
        FOREIGN KEY(product_id) REFERENCES products(id)
    )
    ''')
    conn.commit()
    cur.execute('SELECT * FROM users WHERE username = ?', ('admin',))
    if not cur.fetchone():
        pw = hash_password('admin123')
        cur.execute('INSERT INTO users (username, password_hash) VALUES (?, ?)', ('admin', pw))
        conn.commit()
    conn.close()


def add_user(username, password):
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute('INSERT INTO users (username, password_hash) VALUES (?, ?)', (username, hash_password(password)))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()


def add_product(sku, name, description, price, quantity, min_quantity):
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute('INSERT INTO products (sku,name,description,price,quantity,min_quantity) VALUES (?, ?, ?, ?, ?, ?)',
                    (sku or None, name, description, price, quantity, min_quantity))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()


def update_product(pid, sku, name, description, price, quantity, min_quantity):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute('UPDATE products SET sku=?,name=?,description=?,price=?,quantity=?,min_quantity=? WHERE id=?',
                (sku or None, name, description, price, quantity, min_quantity, pid))
    conn.commit()
    conn.close()


def delete_product(pid):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute('DELETE FROM products WHERE id=?', (pid,))
    conn.commit()
    conn.close()


def get_products(search=None):
    conn = get_conn()
    cur = conn.cursor()
    if search:
        q = f"%{search}%"
        cur.execute('SELECT * FROM products WHERE name LIKE ? OR sku LIKE ? ORDER BY name', (q, q))
    else:
        cur.execute('SELECT * FROM products ORDER BY name')
    rows = cur.fetchall()
    conn.close()
    return rows


def get_product(pid):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute('SELECT * FROM products WHERE id=?', (pid,))
    row = cur.fetchone()
    conn.close()
    return row


def record_sale(product_id, quantity):
    product = get_product(product_id)
    if not product:
        return False, 'Product not found'
    if product['quantity'] < quantity:
        return False, 'Insufficient stock'
    total_price = quantity * product['price']
    sold_at = datetime.datetime.utcnow().isoformat()
    conn = get_conn()
    cur = conn.cursor()
    cur.execute('INSERT INTO sales (product_id, quantity, total_price, sold_at) VALUES (?, ?, ?, ?)',
                (product_id, quantity, total_price, sold_at))
    cur.execute('UPDATE products SET quantity = quantity - ? WHERE id = ?', (quantity, product_id))
    conn.commit()
    conn.close()
    return True, None


def restock_product(product_id, quantity):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute('UPDATE products SET quantity = quantity + ? WHERE id = ?', (quantity, product_id))
    conn.commit()
    conn.close()


def get_low_stock():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute('SELECT * FROM products WHERE quantity <= min_quantity ORDER BY quantity')
    rows = cur.fetchall()
    conn.close()
    return rows


def export_products_csv(path):
    rows = get_products()
    with open(path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['id','sku','name','description','price','quantity','min_quantity'])
        for r in rows:
            writer.writerow([r['id'], r['sku'], r['name'], r['description'], r['price'], r['quantity'], r['min_quantity']])


def export_sales_csv(path):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute('SELECT s.id, p.name, s.quantity, s.total_price, s.sold_at FROM sales s LEFT JOIN products p ON p.id = s.product_id ORDER BY s.sold_at')
    rows = cur.fetchall()
    conn.close()
    with open(path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['id','product','quantity','total_price','sold_at'])
        for r in rows:
            writer.writerow(r)


def sales_summary():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute('SELECT date(s.sold_at) as day, SUM(s.total_price) as total FROM sales s GROUP BY day ORDER BY day')
    rows = cur.fetchall()
    conn.close()
    return rows

class AdvancedInventoryApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title('Inventory Dashboard — Light Theme')
        self.geometry('1100x700')
        self.minsize(900,600)

        # set appearance
        ctk.set_appearance_mode('Light')
        ctk.set_default_color_theme('blue')

        self.current_user = None
        self._build_login()


    def _build_login(self):
        for w in self.winfo_children():
            w.destroy()
        frame = ctk.CTkFrame(self, corner_radius=8, fg_color='transparent')
        frame.pack(expand=True, fill='both', padx=20, pady=20)

        card = ctk.CTkFrame(frame, width=480, height=320, corner_radius=10)
        card.place(relx=0.5, rely=0.5, anchor='center')

        lbl = ctk.CTkLabel(card, text='Inventory Management', font=ctk.CTkFont(size=20, weight='bold'))
        lbl.pack(pady=(20,8))
        sub = ctk.CTkLabel(card, text='Login or Sign up to continue', text_color='#555555')
        sub.pack(pady=(0,12))

        self.username_var = ctk.StringVar()
        self.password_var = ctk.StringVar()

        user_entry = ctk.CTkEntry(card, placeholder_text='Username', textvariable=self.username_var, width=320)
        user_entry.pack(pady=6)
        pw_entry = ctk.CTkEntry(card, placeholder_text='Password', show='*', textvariable=self.password_var, width=320)
        pw_entry.pack(pady=6)

        btn_frame = ctk.CTkFrame(card, fg_color='transparent')
        btn_frame.pack(pady=12)
        login_btn = ctk.CTkButton(btn_frame, text='Login', width=120, command=self._do_login)
        signup_btn = ctk.CTkButton(btn_frame, text='Sign up', width=120, command=self._do_signup)
        login_btn.grid(row=0, column=0, padx=6)
        signup_btn.grid(row=0, column=1, padx=6)

        hint = ctk.CTkLabel(card, text='Default: admin / admin123', text_color='#888888')
        hint.pack(pady=(10,6))

    def _do_login(self):
        username = self.username_var.get().strip()
        password = self.password_var.get().strip()
        if not username or not password:
            messagebox.showwarning('Login', 'Enter username and password')
            return
        conn = get_conn()
        cur = conn.cursor()
        cur.execute('SELECT * FROM users WHERE username = ?', (username,))
        row = cur.fetchone()
        conn.close()
        if not row or not verify_password(password, row['password_hash']):
            messagebox.showerror('Login failed', 'Invalid credentials')
            return
        self.current_user = username
        self._build_main_ui()

    def _do_signup(self):
        username = self.username_var.get().strip()
        password = self.password_var.get().strip()
        if not username or not password:
            messagebox.showwarning('Sign up', 'Enter username and password')
            return
        if add_user(username, password):
            messagebox.showinfo('Sign up', 'User created — you can login now')
        else:
            messagebox.showerror('Sign up', 'Username already exists')


    def _build_main_ui(self):
        for w in self.winfo_children():
            w.destroy()


        top = ctk.CTkFrame(self, height=48)
        top.pack(fill='x')
        user_lbl = ctk.CTkLabel(top, text=f'Logged in as: {self.current_user}', anchor='w')
        user_lbl.pack(side='left', padx=12)
        logout_btn = ctk.CTkButton(top, text='Logout', width=80, command=self._logout)
        logout_btn.pack(side='right', padx=12)


        container = ctk.CTkFrame(self)
        container.pack(fill='both', expand=True, padx=12, pady=12)

        sidebar = ctk.CTkFrame(container, width=220, corner_radius=8)
        sidebar.pack(side='left', fill='y', padx=(0,12), pady=6)

        mainpanel = ctk.CTkFrame(container, corner_radius=8)
        mainpanel.pack(side='left', fill='both', expand=True, pady=6)


        add_btn = ctk.CTkButton(sidebar, text='Add Product', width=180, command=self._open_add_product, fg_color='#2ecc71')
        add_btn.pack(pady=8, padx=12)
        sell_btn = ctk.CTkButton(sidebar, text='Sell Product', width=180, command=self._sell_selected, fg_color='#f39c12')
        sell_btn.pack(pady=8, padx=12)
        restock_btn = ctk.CTkButton(sidebar, text='Restock', width=180, command=self._restock_selected, fg_color='#3498db')
        restock_btn.pack(pady=8, padx=12)
        delete_btn = ctk.CTkButton(sidebar, text='Delete Product', width=180, command=self._delete_selected, fg_color='#e74c3c')
        delete_btn.pack(pady=8, padx=12)

        import_btn = ctk.CTkButton(sidebar, text='Import CSV', width=180, command=self._import_products)
        import_btn.pack(pady=(20,6), padx=12)
        exp_prod_btn = ctk.CTkButton(sidebar, text='Export Products', width=180, command=self._export_products)
        exp_prod_btn.pack(pady=6, padx=12)
        exp_sales_btn = ctk.CTkButton(sidebar, text='Export Sales', width=180, command=self._export_sales)
        exp_sales_btn.pack(pady=6, padx=12)

        low_btn = ctk.CTkButton(sidebar, text='Low Stock Report', width=180, command=self._show_low_stock)
        low_btn.pack(pady=(20,6), padx=12)


        search_frame = ctk.CTkFrame(mainpanel)
        search_frame.pack(fill='x', padx=8, pady=8)
        self.search_var = ctk.StringVar()
        search_entry = ctk.CTkEntry(search_frame, placeholder_text='Search by name or SKU', textvariable=self.search_var)
        search_entry.pack(side='left', fill='x', expand=True, padx=(8,4))
        search_btn = ctk.CTkButton(search_frame, text='Search', width=100, command=self._do_search)
        search_btn.pack(side='left', padx=4)
        refresh_btn = ctk.CTkButton(search_frame, text='Refresh', width=100, command=self._refresh_table)
        refresh_btn.pack(side='left', padx=4)


        table_frame = ctk.CTkFrame(mainpanel)
        table_frame.pack(fill='both', expand=True, padx=8, pady=(0,8))
        cols = ('id','sku','name','price','quantity','min_quantity')
        tree = ttk.Treeview(table_frame, columns=cols, show='headings', selectmode='browse')
        for c in cols:
            tree.heading(c, text=c.title())
            tree.column(c, anchor='center')
        vsb = ttk.Scrollbar(table_frame, orient='vertical', command=tree.yview)
        tree.configure(yscrollcommand=vsb.set)
        tree.pack(side='left', fill='both', expand=True)
        vsb.pack(side='right', fill='y')
        self.tree = tree

        # bottom chart area
        chart_frame = ctk.CTkFrame(self, height=220)
        chart_frame.pack(fill='x', padx=12, pady=(0,12))
        chart_label = ctk.CTkLabel(chart_frame, text='Sales Over Time', font=ctk.CTkFont(size=14, weight='bold'))
        chart_label.pack(anchor='w', padx=12, pady=(6,0))
        self._chart_container = ctk.CTkFrame(chart_frame, fg_color='transparent')
        self._chart_container.pack(fill='both', expand=True, padx=8, pady=6)

        self._populate_table()
        self._draw_chart()

    def _logout(self):
        self.current_user = None
        self._build_login()


    def _populate_table(self, search=None):
        for r in self.tree.get_children():
            self.tree.delete(r)
        rows = get_products(search)
        for r in rows:
            vals = (r['id'], r['sku'] or '', r['name'], f"{r['price']:.2f}", r['quantity'], r['min_quantity'])
            iid = self.tree.insert('', 'end', values=vals)
            if r['quantity'] <= r['min_quantity']:
                self.tree.item(iid, tags=('low',))
        self.tree.tag_configure('low', background='#ffecec')

    def _refresh_table(self):
        self._populate_table(self.search_var.get().strip() or None)
        self._draw_chart()

    def _do_search(self):
        self._populate_table(self.search_var.get().strip() or None)


    def _open_add_product(self):
        dlg = ProductDialog(self, 'Add Product')
        self.wait_window(dlg)
        if dlg.result:
            sku, name, desc, price, qty, minq = dlg.result
            ok = add_product(sku, name, desc, price, qty, minq)
            if not ok:
                messagebox.showerror('Error', 'SKU must be unique')
            self._refresh_table()

    def _get_selected_pid(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showwarning('Select', 'Select a product')
            return None
        pid = self.tree.item(sel[0])['values'][0]
        return pid

    def _delete_selected(self):
        pid = self._get_selected_pid()
        if not pid:
            return
        if messagebox.askyesno('Confirm', 'Delete product?'):
            delete_product(pid)
            self._refresh_table()

    def _sell_selected(self):
        pid = self._get_selected_pid()
        if not pid:
            return
        product = get_product(pid)
        qty = simpledialog.askinteger('Sell', f"Quantity to sell (Available: {product['quantity']})", minvalue=1)
        if qty:
            ok, err = record_sale(pid, qty)
            if not ok:
                messagebox.showerror('Error', err)
            else:
                messagebox.showinfo('Sold', 'Sale recorded')
            self._refresh_table()

    def _restock_selected(self):
        pid = self._get_selected_pid()
        if not pid:
            return
        qty = simpledialog.askinteger('Restock', 'Quantity to add', minvalue=1)
        if qty:
            restock_product(pid, qty)
            messagebox.showinfo('Restock', 'Product restocked')
            self._refresh_table()


    def _import_products(self):
        path = filedialog.askopenfilename(filetypes=[('CSV Files','*.csv')])
        if not path:
            return
        with open(path, newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            count = 0
            for row in reader:
                try:
                    sku = row.get('sku') or row.get('SKU')
                    name = row.get('name')
                    desc = row.get('description','')
                    price = float(row.get('price') or 0)
                    qty = int(float(row.get('quantity') or 0))
                    minq = int(float(row.get('min_quantity') or row.get('min') or 5))
                    if name:
                        add_product(sku, name, desc, price, qty, minq)
                        count += 1
                except Exception:
                    continue
        messagebox.showinfo('Import', f'Imported {count} products')
        self._refresh_table()

    def _export_products(self):
        path = filedialog.asksaveasfilename(defaultextension='.csv', filetypes=[('CSV Files','*.csv')])
        if not path:
            return
        export_products_csv(path)
        messagebox.showinfo('Export', 'Products exported')

    def _export_sales(self):
        path = filedialog.asksaveasfilename(defaultextension='.csv', filetypes=[('CSV Files','*.csv')])
        if not path:
            return
        export_sales_csv(path)
        messagebox.showinfo('Export', 'Sales exported')


    def _show_low_stock(self):
        rows = get_low_stock()
        if not rows:
            messagebox.showinfo('Low Stock', 'No low stock items')
            return
        msg = '\n'.join([f"{r['name']} (qty: {r['quantity']}, min: {r['min_quantity']})" for r in rows])
        messagebox.showwarning('Low Stock Items', msg)


    def _draw_chart(self):
        for w in self._chart_container.winfo_children():
            w.destroy()
        data = sales_summary()
        if not data:
            lbl = ctk.CTkLabel(self._chart_container, text='No sales data yet', text_color='#666666')
            lbl.pack(padx=12, pady=12)
            return
        days = [row[0] for row in data]
        totals = [row[1] for row in data]
        fig = plt.Figure(figsize=(9,2.4), dpi=100)
        ax = fig.add_subplot(111)
        ax.plot(days, totals, marker='o')
        ax.set_title('Sales Over Time')
        ax.set_xlabel('Day')
        ax.set_ylabel('Total Sales')
        fig.autofmt_xdate(rotation=30)
        canvas = FigureCanvasTkAgg(fig, master=self._chart_container)
        canvas.draw()
        widget = canvas.get_tk_widget()
        widget.pack(fill='both', expand=True)



class ProductDialog(ctk.CTkToplevel):
    def __init__(self, parent, title, product=None):
        super().__init__(parent)
        self.title(title)
        self.result = None
        self.geometry('480x320')
        self.transient(parent)
        self.grab_set()

        frm = ctk.CTkFrame(self, corner_radius=8)
        frm.pack(fill='both', expand=True, padx=12, pady=12)

        self.sku_var = ctk.StringVar(value=product['sku'] if product else '')
        self.name_var = ctk.StringVar(value=product['name'] if product else '')
        self.desc_var = ctk.StringVar(value=product['description'] if product else '')
        self.price_var = ctk.StringVar(value=str(product['price']) if product else '0.0')
        self.qty_var = ctk.StringVar(value=str(product['quantity']) if product else '0')
        self.min_var = ctk.StringVar(value=str(product['min_quantity']) if product else '5')

        rows = [
            ('SKU', self.sku_var), ('Name', self.name_var), ('Description', self.desc_var),
            ('Price', self.price_var), ('Quantity', self.qty_var), ('Min Quantity', self.min_var)
        ]
        for label, var in rows:
            r = ctk.CTkFrame(frm, fg_color='transparent')
            r.pack(fill='x', pady=4)
            ctk.CTkLabel(r, text=label, width=12).pack(side='left', padx=(0,8))
            ctk.CTkEntry(r, textvariable=var).pack(side='left', fill='x', expand=True)

        btn_frame = ctk.CTkFrame(frm, fg_color='transparent')
        btn_frame.pack(pady=12)
        save_btn = ctk.CTkButton(btn_frame, text='Save', width=100, command=self._on_save)
        cancel_btn = ctk.CTkButton(btn_frame, text='Cancel', width=100, command=self.destroy)
        save_btn.grid(row=0, column=0, padx=8)
        cancel_btn.grid(row=0, column=1, padx=8)

    def _on_save(self):
        try:
            sku = self.sku_var.get().strip() or None
            name = self.name_var.get().strip()
            desc = self.desc_var.get().strip()
            price = float(self.price_var.get())
            qty = int(float(self.qty_var.get()))
            minq = int(float(self.min_var.get()))
            if not name:
                messagebox.showwarning('Validation', 'Name required')
                return
            self.result = (sku, name, desc, price, qty, minq)
            self.destroy()
        except Exception:
            messagebox.showerror('Validation', 'Invalid numeric values')



if __name__ == '__main__':
    init_db()
    app = AdvancedInventoryApp()
    app.mainloop()
