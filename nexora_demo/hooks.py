import logging
from datetime import timedelta

from odoo import Command, fields

_logger = logging.getLogger(__name__)

# 1x1 PNG used as a placeholder signature
PNG = ('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==')


def post_init_hook(env):
    icp = env['ir.config_parameter'].sudo()
    if icp.get_param('nexora_demo.loaded'):
        _logger.info("Nexora demo: data already loaded, skipping.")
        return
    demo = NexoraDemo(env)
    sections = [
        ('core master data', demo.core),
        ('warehouses, locations & stock', demo.warehouse),
        ('inventory history & analysis', demo.inventory),
        ('fleet', demo.fleet),
        ('fuel & expenses', demo.fuel),
        ('maintenance', demo.maintenance),
        ('transport', demo.transport),
        ('procurement', demo.procurement),
    ]
    for label, method in sections:
        try:
            with env.cr.savepoint():
                method()
            _logger.info("Nexora demo: section '%s' loaded.", label)
        except Exception:
            _logger.exception("Nexora demo: section '%s' FAILED.", label)
    icp.set_param('nexora_demo.loaded', '1')


class NexoraDemo:

    def __init__(self, env):
        self.env = env(context=dict(
            env.context, tracking_disable=True, mail_create_nolog=True, mail_notrack=True))
        self.now = fields.Datetime.now()
        self.today = fields.Date.today()
        self.admin = self.env.ref('base.user_admin')
        self.jo = self.env.ref('base.jo', raise_if_not_found=False)
        self.wh_main = self.env['stock.warehouse'].search(
            [('company_id', '=', self.env.company.id)], limit=1)

    # ---------------------------------------------------------------- helpers
    def hours(self, n):
        return self.now + timedelta(hours=n)

    def days(self, n):
        return self.today + timedelta(days=n)

    def partner(self, name, city, **kw):
        vals = {'name': name, 'city': city, 'is_company': True,
                'country_id': self.jo.id if self.jo else False}
        vals.update(kw)
        return self.env['res.partner'].create(vals)

    def product(self, name, ptype='consu', **kw):
        vals = {'name': name, 'type': ptype}
        if ptype == 'consu':
            vals['is_storable'] = True
        vals.update(kw)
        return self.env['product.template'].create(vals)

    def pv(self, key):
        return self.prod[key].product_variant_id

    @staticmethod
    def uom_field(model):
        return 'product_uom_id' if 'product_uom_id' in model._fields else 'product_uom'

    # ------------------------------------------------------------------ core
    def core(self):
        env = self.env
        env.company.write({'nexora_branch_code': 'HQ-AMM', 'nexora_branch_type': 'hq'})

        CC = env['nexora.cost.center']
        root = CC.create({'name': 'Nexora Operations', 'code': 'NX-OPS', 'center_type': 'operations'})
        self.cc = {'root': root}
        for key, name, code, ctype in [
                ('wh', 'Warehousing', 'OPS-WH', 'warehouse'),
                ('tr', 'Transportation', 'OPS-TR', 'transport'),
                ('fl', 'Fleet', 'OPS-FL', 'fleet'),
                ('sa', 'Sales', 'OPS-SA', 'sales'),
                ('ad', 'Administration', 'OPS-AD', 'admin')]:
            self.cc[key] = CC.create({
                'name': name, 'code': code, 'center_type': ctype, 'parent_id': root.id})

        self.cust = {
            'noor': self.partner('Al-Noor Supermarkets', 'Amman', is_nexora_customer=True,
                                 phone='+962 6 555 0101', email='orders@alnoor.example'),
            'petra': self.partner('Petra Pharma', 'Amman', is_nexora_customer=True,
                                  phone='+962 6 555 0102', email='supply@petrapharma.example'),
            'fresh': self.partner('Jordan Fresh Foods', 'Zarqa', is_nexora_customer=True,
                                  phone='+962 5 555 0103', email='logistics@jofresh.example'),
            'aqaba': self.partner('Aqaba Industrial Co.', 'Aqaba', is_nexora_customer=True,
                                  phone='+962 3 555 0104', email='plant@aqabaindustrial.example'),
            'cosmetics': self.partner('Dead Sea Cosmetics', 'Amman', is_nexora_customer=True,
                                      phone='+962 6 555 0105', email='ship@dscosmetics.example'),
            'builders': self.partner('Amman Builders', 'Amman', is_nexora_customer=True,
                                     phone='+962 6 555 0106', email='site@ammanbuilders.example'),
        }
        self.addr = {}
        for key, parent, name, city in [
                ('noor_irbid', 'noor', 'Al-Noor - Irbid Branch', 'Irbid'),
                ('fresh_aqaba', 'fresh', 'Jordan Fresh - Aqaba Kitchen', 'Aqaba'),
                ('petra_zarqa', 'petra', 'Petra Pharma - Zarqa Pharmacy', 'Zarqa'),
                ('builders_site', 'builders', 'Amman Builders - Sahab Site', 'Sahab'),
                ('cosm_amman', 'cosmetics', 'Dead Sea Cosmetics - Amman Outlet', 'Amman'),
                ('aqaba_plant', 'aqaba', 'Aqaba Industrial - Plant Gate', 'Aqaba')]:
            self.addr[key] = env['res.partner'].create({
                'name': name, 'parent_id': self.cust[parent].id, 'type': 'delivery',
                'city': city, 'country_id': self.jo.id if self.jo else False})

        self.vend = {
            'fuel': self.partner('Jordan Fuel Stations', 'Amman', is_nexora_vendor=True,
                                 phone='+962 6 555 0201'),
            'tires': self.partner('Gulf Tires & Parts', 'Zarqa', is_nexora_vendor=True,
                                  phone='+962 5 555 0202'),
            'oil': self.partner('Delta Lubricants', 'Amman', is_nexora_vendor=True,
                                phone='+962 6 555 0203'),
            'pack': self.partner('Pack & Wrap Supplies', 'Amman', is_nexora_vendor=True,
                                 phone='+962 6 555 0204'),
            'workshop': self.partner('Al-Amal Workshop', 'Zarqa', is_nexora_vendor=True,
                                     phone='+962 5 555 0205'),
            'pallets': self.partner('Levant Pallets Co.', 'Amman', is_nexora_vendor=True,
                                    phone='+962 6 555 0206'),
        }

        self.drivers = {}
        for key, name, lic, cls, exp in [
                ('ahmad', 'Ahmad Haddad', 'JO-DL-1001', 'd', 400),
                ('khaled', 'Khaled Mansour', 'JO-DL-1002', 'c', 300),
                ('omar', 'Omar Nasser', 'JO-DL-1003', 'c', 500),
                ('yousef', 'Yousef Khalil', 'JO-DL-1004', 'd', 250),
                ('sami', 'Sami Barakat', 'JO-DL-1005', 'c', 12),      # expiring soon
                ('layth', 'Layth Qasem', 'JO-DL-1006', 'b', -20)]:    # expired
            self.drivers[key] = env['hr.employee'].create({
                'name': name, 'is_driver': True, 'driver_license_no': lic,
                'license_class': cls, 'license_expiry': self.days(exp)})

        P = self.product
        self.prod = {
            'water': P('Bottled Water 1.5L (6-pack)', weight=9, volume=0.012, list_price=3.5,
                       standard_price=2.4, barcode='NXD-WATER', nexora_temperature_class='ambient'),
            'chicken': P('Frozen Chicken Carton 10kg', weight=10, volume=0.02, list_price=28,
                         standard_price=21, barcode='NXD-CHICKEN', nexora_temperature_class='frozen'),
            'yogurt': P('Dairy Yogurt Crate', weight=12, volume=0.03, list_price=18,
                        standard_price=13, barcode='NXD-YOGURT', nexora_temperature_class='chilled'),
            'pharma': P('Pharma Antibiotics Box', weight=2, volume=0.01, list_price=120,
                        standard_price=90, barcode='NXD-PHARMA', nexora_temperature_class='chilled'),
            'solvent': P('Industrial Solvent 20L Drum', weight=22, volume=0.025, list_price=65,
                         standard_price=48, barcode='NXD-SOLVENT', nexora_hazardous=True),
            'rebar': P('Steel Rebar Bundle (500kg)', weight=500, volume=0.4, list_price=420,
                       standard_price=360, barcode='NXD-REBAR'),
            'cosm': P('Cosmetics Carton', weight=5, volume=0.02, list_price=150,
                      standard_price=95, barcode='NXD-COSM'),
            'oil': P('Engine Oil 15W40 (20L)', list_price=60, standard_price=46, barcode='NXD-OIL'),
            'tire': P('Truck Tire 295/80R22.5', list_price=260, standard_price=215, barcode='NXD-TIRE'),
            'brake': P('Heavy Brake Pad Set', list_price=180, standard_price=140, barcode='NXD-BRAKE'),
            'wrap': P('Pallet Stretch Wrap Roll', list_price=5, standard_price=4, barcode='NXD-WRAP'),
            'pallet': P('Wooden Pallet', list_price=14, standard_price=11, barcode='NXD-PALLET'),
            'svc_tr': P('Local Transport (per trip)', 'service', list_price=90),
            'svc_cold': P('Cold Chain Surcharge', 'service', list_price=35),
            'svc_wh': P('Warehousing (per pallet / day)', 'service', list_price=2.5),
        }

        def contract(partner, title, ctype, stype, start, end, lines):
            c = env['nexora.contract'].create({
                'title': title, 'partner_id': partner.id, 'contract_type': ctype,
                'service_type': stype, 'date_start': self.days(start),
                'date_end': self.days(end) if end else False,
                'responsible_id': self.admin.id, 'cost_center_id': self.cc['sa'].id,
                'line_ids': [Command.create({
                    'product_id': self.pv(k).id, 'name': self.prod[k].name,
                    'price_unit': price, 'min_quantity': qty}) for k, price, qty in lines]})
            c.action_activate()
            return c

        self.contracts = {
            'noor': contract(self.cust['noor'], 'Al-Noor Annual Transport Agreement',
                             'customer', 'transport', -30, 335, [('svc_tr', 85, 10)]),
            'fresh': contract(self.cust['fresh'], 'Jordan Fresh Cold Chain Agreement',
                              'customer', 'transport', -340, 20,           # expires in 20 days
                              [('svc_tr', 110, 5), ('svc_cold', 35, 5)]),
            'petra': contract(self.cust['petra'], 'Petra Pharma Temperature-Controlled Transport',
                              'customer', 'transport', -90, 275, [('svc_tr', 120, 4), ('svc_cold', 40, 4)]),
            'aqaba': contract(self.cust['aqaba'], 'Aqaba Industrial Warehousing & Delivery',
                              'customer', 'warehousing', -60, 305, [('svc_wh', 2.5, 100)]),
            'fuel': contract(self.vend['fuel'], 'Fuel Supply Agreement - Jordan Fuel Stations',
                             'vendor', 'supply', -10, 355, []),
        }

    # ------------------------------------------------------------- warehouse
    def warehouse(self):
        env = self.env
        wh = self.wh_main
        wh.write({'nexora_warehouse_type': 'central', 'nexora_cost_center_id': self.cc['wh'].id})
        Wh = env['stock.warehouse']
        self.wh_zrq = Wh.create({
            'name': 'Zarqa Logistics Hub', 'code': 'ZRQ', 'nexora_warehouse_type': 'regional',
            'nexora_cost_center_id': self.cc['wh'].id})
        self.wh_aqb = Wh.create({
            'name': 'Aqaba Cold Storage', 'code': 'AQB', 'nexora_warehouse_type': 'cold',
            'nexora_cost_center_id': self.cc['wh'].id})

        def loc(w, name, barcode, ltype, **kw):
            vals = {'name': name, 'location_id': w.lot_stock_id.id, 'usage': 'internal',
                    'barcode': barcode, 'nexora_location_type': ltype}
            vals.update(kw)
            return env['stock.location'].create(vals)

        self.loc = {
            'amb': loc(wh, 'A-01-AMBIENT', 'LOC-WH-A01', 'storage', nexora_temperature_class='ambient',
                       nexora_enforce_rules=True, nexora_max_weight=15000, nexora_max_volume=40),
            'haz': loc(wh, 'B-01-HAZMAT', 'LOC-WH-B01', 'storage', nexora_temperature_class='ambient',
                       nexora_allow_hazardous=True, nexora_enforce_rules=True,
                       nexora_max_weight=3000, nexora_max_volume=10),
            'chill': loc(wh, 'C-01-CHILLED', 'LOC-WH-C01', 'storage', nexora_temperature_class='chilled',
                         nexora_enforce_rules=True, nexora_max_weight=8000, nexora_max_volume=40),
            'froz': loc(wh, 'D-01-FROZEN', 'LOC-WH-D01', 'storage', nexora_temperature_class='frozen',
                        nexora_enforce_rules=True, nexora_max_weight=8000, nexora_max_volume=20),
            'dock': loc(wh, 'REC-DOCK', 'LOC-WH-REC', 'receiving'),
            'zrq': loc(self.wh_zrq, 'Z-01-YARD', 'LOC-ZRQ-Y01', 'storage',
                       nexora_temperature_class='ambient', nexora_enforce_rules=True,
                       nexora_max_weight=30000, nexora_max_volume=60),
            'aq_chill': loc(self.wh_aqb, 'Q-01-CHILLED', 'LOC-AQB-Q01', 'storage',
                            nexora_temperature_class='chilled', nexora_enforce_rules=True,
                            nexora_max_weight=6000, nexora_max_volume=30),
            'aq_froz': loc(self.wh_aqb, 'Q-02-FROZEN', 'LOC-AQB-Q02', 'storage',
                           nexora_temperature_class='frozen', nexora_enforce_rules=True,
                           nexora_max_weight=6000, nexora_max_volume=30),
        }

        Quant = env['stock.quant']
        for key, loc_key, qty in [
                ('water', 'amb', 750), ('cosm', 'amb', 400), ('oil', 'amb', 40), ('tire', 'amb', 12),
                ('brake', 'amb', 6), ('wrap', 'amb', 60), ('pallet', 'amb', 200),
                ('solvent', 'haz', 100), ('yogurt', 'chill', 200), ('pharma', 'chill', 1120),
                ('chicken', 'froz', 450), ('rebar', 'zrq', 30)]:
            Quant._update_available_quantity(self.pv(key), self.loc[loc_key], qty)

        session = env['nexora.scan.session'].create({
            'operation': 'receive', 'warehouse_id': wh.id,
            'location_dest_id': self.loc['amb'].id, 'partner_id': self.vend['pack'].id,
            'line_ids': [Command.create({'product_id': self.pv('wrap').id, 'qty': 40})]})
        session.action_validate()

    # ------------------------------------------------------------- inventory
    def _deliver(self, product_key, qty, days_ago, customer):
        env, wh = self.env, self.wh_main
        product = self.pv(product_key)
        dest = env.ref('stock.stock_location_customers')
        picking = env['stock.picking'].create({
            'picking_type_id': wh.out_type_id.id, 'partner_id': customer.id,
            'location_id': wh.lot_stock_id.id, 'location_dest_id': dest.id})
        Move = env['stock.move']
        vals = {
            'product_id': product.id, 'product_uom_qty': qty, 'picking_id': picking.id,
            'location_id': wh.lot_stock_id.id, 'location_dest_id': dest.id,
            self.uom_field(Move): product.uom_id.id}
        if 'name' in Move._fields:
            vals['name'] = product.display_name
        Move.create(vals)
        picking.action_confirm()
        picking.action_assign()
        for move in picking.move_ids:
            move.quantity = move.product_uom_qty
            move.picked = True
        picking.with_context(skip_backorder=True, skip_sms=True).button_validate()
        when = self.now - timedelta(days=days_ago)
        picking.move_ids.write({'date': when})
        picking.move_ids.move_line_ids.write({'date': when})
        picking.write({'date_done': when})

    def inventory(self):
        env = self.env
        history = {
            # product: (quantities, days ago)  -> water ends critical, yogurt stock-out,
            # chicken/solvent healthy, pharma overstock, cosmetics = no demand
            'water': ([60, 55, 70, 58, 62, 50, 65, 57, 60, 68, 52, 43],
                      [58, 53, 48, 43, 38, 33, 28, 23, 18, 13, 8, 3]),
            'yogurt': ([25, 20, 30, 25, 25, 20, 30, 25], [56, 49, 42, 35, 28, 21, 14, 7]),
            'chicken': ([40, 35, 45, 30, 40, 35, 40, 35], [57, 50, 43, 36, 29, 22, 15, 8]),
            'solvent': ([10, 5, 10, 5, 10], [50, 40, 30, 20, 10]),
            'pharma': ([20, 15, 25, 20, 20, 20], [55, 45, 35, 25, 15, 5]),
        }
        customers = list(self.cust.values())
        i = 0
        for key, (qtys, days) in history.items():
            for qty, d in zip(qtys, days):
                self._deliver(key, qty, d, customers[i % len(customers)])
                i += 1
        Analysis = env['nexora.inventory.analysis']
        Analysis._run_for_warehouse(self.wh_main, **Analysis._nexora_default_params())
        plan = env['nexora.replenishment.plan']._create_from_analysis(self.wh_main)
        if plan:
            plan._notify_responsible()

    # ----------------------------------------------------------------- fleet
    def fleet(self):
        env = self.env
        Brand, Model = env['fleet.vehicle.model.brand'], env['fleet.vehicle.model']

        def vmodel(brand, name):
            b = Brand.search([('name', '=', brand)], limit=1) or Brand.create({'name': brand})
            return Model.search([('name', '=', name), ('brand_id', '=', b.id)], limit=1) \
                or Model.create({'name': name, 'brand_id': b.id})

        # key, plate, brand, model, class, payload kg, volume m3, temp, hazmat, reg, ins, insp (days), odometer
        specs = [
            ('v1', '20-10001', 'Isuzu', 'NPR 75', 'truck_light', 3000, 18, 'ambient', False, 300, 200, 150, 12000),
            ('v2', '20-10002', 'Mercedes-Benz', 'Actros 1845', 'truck_heavy', 24000, 80, 'ambient', True, 330, 220, 170, 80000),
            ('v3', '20-10003', 'Hyundai', 'H350 Refrigerated Van', 'van', 1200, 10, 'chilled', False, 280, 190, 25, 30000),
            ('v4', '20-10004', 'Mitsubishi', 'Canter FE Frozen', 'refrigerated', 3500, 20, 'frozen', False, 350, 240, 160, 45000),
            ('v5', '20-10005', 'Isuzu', 'D-Max Pickup', 'pickup', 900, 3, 'ambient', False, 310, -10, 140, 60000),
            ('v6', '20-10006', 'Mercedes-Benz', 'Atego 1523', 'truck_heavy', 9000, 40, 'ambient', True, 290, 210, 130, 95000),
        ]
        self.veh = {}
        for key, plate, brand, model, cls, payload, vol, temp, haz, reg, ins, insp, odo in specs:
            vehicle = env['fleet.vehicle'].create({
                'license_plate': plate, 'model_id': vmodel(brand, model).id, 'fuel_type': 'diesel',
                'nexora_vehicle_class': cls, 'nexora_max_payload': payload,
                'nexora_cargo_volume': vol, 'nexora_axles': 2 if payload < 5000 else 3,
                'nexora_temperature_class': temp, 'nexora_hazmat_certified': haz,
                'nexora_registration_no': f'REG-{plate}', 'nexora_registration_expiry': self.days(reg),
                'nexora_insurance_policy': f'POL-{plate}', 'nexora_insurance_expiry': self.days(ins),
                'nexora_inspection_expiry': self.days(insp),
                'nexora_home_warehouse_id': self.wh_main.id,
                'nexora_cost_center_id': self.cc['fl'].id})
            env['fleet.vehicle.odometer'].create({
                'vehicle_id': vehicle.id, 'value': odo, 'date': self.days(-70)})
            self.veh[key] = vehicle
        self.veh['v1'].nexora_target_consumption = 15
        self.veh['v2'].nexora_target_consumption = 32
        self.veh['v3'].nexora_target_consumption = 12

        Inc = env['nexora.vehicle.incident']
        minor = Inc.create({
            'vehicle_id': self.veh['v1'].id, 'driver_id': self.drivers['sami'].id,
            'incident_date': self.hours(-24 * 25), 'incident_type': 'breakdown', 'severity': 'minor',
            'location': 'Amman - Airport Road', 'description': 'Alternator failure, vehicle towed.',
            'estimated_cost': 180, 'actual_cost': 165})
        minor.action_investigate()
        minor.resolution_note = 'Alternator replaced at the external workshop.'
        minor.action_resolve()
        self.incident_major = Inc.create({
            'vehicle_id': self.veh['v6'].id, 'driver_id': self.drivers['layth'].id,
            'incident_date': self.hours(-30), 'incident_type': 'accident', 'severity': 'major',
            'location': 'Desert Highway km 112',
            'description': 'Rear-end collision with a passenger car. No injuries.',
            'police_report_no': 'PR-88231', 'estimated_cost': 4500,
            'insurance_claim': True, 'claim_reference': 'CLM-2026-0457'})

    # ------------------------------------------------------------------ fuel
    def fuel(self):
        env = self.env
        cards = {}
        for key, name, vkey, limit, exp in [
                ('c1', 'FC-1001', 'v1', 800, 200), ('c2', 'FC-1002', 'v2', 2500, 330),
                ('c3', 'FC-1003', 'v3', 150, 20)]:
            cards[key] = env['nexora.fuel.card'].create({
                'name': name, 'provider_id': self.vend['fuel'].id, 'vehicle_id': self.veh[vkey].id,
                'monthly_limit': limit, 'expiry_date': self.days(exp),
                'responsible_id': self.admin.id})
        logs = [
            ('v1', 'c1', [(50, 12400, 58), (40, 12800, 57), (30, 13210, 61),
                          (20, 13600, 55), (10, 14005, 62), (3, 14300, 92)]),   # last = abnormal
            ('v2', 'c2', [(45, 80500, 280), (25, 81400, 290), (8, 82350, 305)]),
            ('v3', 'c3', [(20, 30500, 95), (12, 30900, 92), (5, 31300, 70)]),   # exceeds card limit
        ]
        for vkey, ckey, rows in logs:
            for days_ago, odo, liters in rows:
                log = env['nexora.fuel.log'].create({
                    'vehicle_id': self.veh[vkey].id, 'date': self.days(-days_ago), 'odometer': odo,
                    'quantity': liters, 'price_unit': 0.84, 'full_tank': True,
                    'station_id': self.vend['fuel'].id, 'card_id': cards[ckey].id})
                log.action_confirm()
        for vkey, etype, desc, amount, d in [
                ('v1', 'toll', 'Highway tolls - Aqaba trip', 18.5, 12),
                ('v2', 'toll', 'Desert highway tolls', 42, 9),
                ('v3', 'parking', 'Parking - city deliveries', 6, 4),
                ('v5', 'fine', 'Speeding fine', 50, 15),
                ('v1', 'tires', 'Tire repair', 35, 20),
                ('v4', 'cleaning', 'Cold box sanitizing', 25, 6)]:
            expense = env['nexora.vehicle.expense'].create({
                'vehicle_id': self.veh[vkey].id, 'expense_type': etype, 'description': desc,
                'amount': amount, 'date': self.days(-d)})
            expense.action_confirm()

    # ----------------------------------------------------------- maintenance
    def maintenance(self):
        env = self.env
        Plan, Order = env['nexora.maintenance.plan'], env['nexora.maintenance.order']
        v = self.veh
        p1 = Plan.create({
            'name': 'Oil & filter change', 'vehicle_id': v['v1'].id, 'trigger_type': 'both',
            'interval_km': 10000, 'interval_days': 180, 'last_done_odometer': 3500,
            'last_done_date': self.days(-170), 'estimated_cost': 180,
            'responsible_id': self.admin.id,
            'description': 'Replace engine oil, oil filter and air filter. Check all fluids.'})        # overdue
        Plan.create({
            'name': 'Tire rotation & alignment', 'vehicle_id': v['v2'].id, 'trigger_type': 'both',
            'interval_km': 20000, 'interval_days': 365, 'last_done_odometer': 62700,
            'last_done_date': self.days(-300), 'estimated_cost': 320,
            'responsible_id': self.admin.id})                                                          # due soon
        Plan.create({
            'name': 'Annual safety inspection', 'vehicle_id': v['v3'].id, 'trigger_type': 'days',
            'interval_days': 365, 'last_done_date': self.days(-355), 'estimated_cost': 90,
            'responsible_id': self.admin.id})                                                          # due soon
        p4 = Plan.create({
            'name': 'Refrigeration unit service', 'vehicle_id': v['v4'].id, 'trigger_type': 'both',
            'interval_km': 15000, 'interval_days': 90, 'last_done_odometer': v['v4'].odometer,
            'last_done_date': self.days(-30), 'estimated_cost': 250,
            'responsible_id': self.admin.id})

        o1 = Order.create({
            'vehicle_id': v['v4'].id, 'order_type': 'preventive', 'plan_id': p4.id,
            'description': 'Quarterly refrigeration unit service', 'workshop_type': 'external',
            'vendor_id': self.vend['workshop'].id, 'scheduled_date': self.hours(-48),
            'line_ids': [
                Command.create({'line_type': 'labor', 'name': 'Technician labor (3h)',
                                'quantity': 3, 'price_unit': 25}),
                Command.create({'line_type': 'part', 'product_id': self.pv('oil').id,
                                'name': 'Compressor oil', 'quantity': 2, 'price_unit': 45})]})
        o1.action_schedule()
        o1.action_start()
        o1.result_note = 'Refrigerant level checked, filters and compressor oil replaced.'
        o1.action_done()                                      # creates a confirmed 'repair' expense

        self.incident_major.action_create_maintenance_order()
        o2 = self.incident_major.maintenance_order_ids[:1]
        o2.write({'line_ids': [
            Command.create({'line_type': 'part', 'name': 'Rear bumper & body repair',
                            'quantity': 1, 'price_unit': 2800}),
            Command.create({'line_type': 'part', 'name': 'Radiator', 'quantity': 1,
                            'price_unit': 650})]})
        o2.action_start()                                     # in progress

        o3 = Order.create({
            'vehicle_id': v['v1'].id, 'order_type': 'preventive', 'plan_id': p1.id,
            'description': 'Oil & filter change (overdue)', 'workshop_type': 'internal',
            'scheduled_date': self.hours(72)})
        o3.action_schedule()

    # ------------------------------------------------------------- transport
    def _order(self, customer, addr, lines, pickup_h, delivery_h, contract=None,
               priority='normal', confirm=True):
        cmds = []
        for key, qty in lines:
            t = self.prod[key]
            cmds.append(Command.create({
                'product_id': t.product_variant_id.id, 'name': t.name, 'quantity': qty,
                'uom_id': t.uom_id.id, 'weight': t.weight * qty, 'volume': t.volume * qty,
                'temperature_class': t.nexora_temperature_class or 'ambient',
                'hazardous': t.nexora_hazardous}))
        order = self.env['nexora.transport.order'].create({
            'partner_id': customer.id, 'delivery_partner_id': addr.id,
            'contract_id': contract.id if contract else False,
            'origin_warehouse_id': self.wh_main.id,
            'requested_pickup_date': self.hours(pickup_h),
            'requested_delivery_date': self.hours(delivery_h),
            'priority': priority, 'cost_center_id': self.cc['tr'].id,
            'responsible_id': self.admin.id, 'line_ids': cmds})
        if confirm:
            order.action_confirm()
        return order

    def _shipment(self, order):
        order.action_create_shipment()
        return order.shipment_ids.sorted('id')[-1]

    def _trip(self, vehicle, driver, shipments, start_h, end_h, route):
        trip = self.env['nexora.transport.trip'].create({
            'vehicle_id': vehicle.id, 'driver_id': driver.id,
            'origin_warehouse_id': self.wh_main.id, 'route': route,
            'planned_start': self.hours(start_h), 'planned_end': self.hours(end_h),
            'responsible_id': self.admin.id})
        shipments.write({'trip_id': trip.id})
        trip.action_plan()
        return trip

    def _pod(self, shipment, receiver, note):
        shipment.write({'pod_receiver_name': receiver, 'pod_note': note, 'pod_signature': PNG})

    def transport(self):
        env, v, d, c, a = self.env, self.veh, self.drivers, self.cust, self.addr

        # 1) delivered on time - frozen chicken on the frozen truck
        o1 = self._order(c['fresh'], a['fresh_aqaba'], [('chicken', 150)], -32, -24,
                         contract=self.contracts['fresh'])
        s1 = self._shipment(o1)
        t1 = self._trip(v['v4'], d['ahmad'], s1, -34, -20, 'Amman - Aqaba (Desert Highway)')
        t1.action_start()
        self._pod(s1, 'Mahmoud Saleh', 'Received at kitchen loading bay. Temperature OK (-18C).')
        s1.action_deliver()
        s1.planned_delivery_date = self.hours(2)
        t1.odometer_end = t1.odometer_start + 330
        t1.action_done()

        # 5) delivered LATE (7h after plan)
        o5 = self._order(c['cosmetics'], a['cosm_amman'], [('cosm', 60)], -56, -50)
        s5 = self._shipment(o5)
        t5 = self._trip(v['v1'], d['sami'], s5, -54, -46, 'Amman local round')
        t5.action_start()
        self._pod(s5, 'Rana Ahmad', 'Delivered to the outlet manager.')
        s5.action_deliver()
        s5.planned_delivery_date = self.hours(-7)
        t5.odometer_end = t5.odometer_start + 42
        t5.action_done()

        # 4) FAILED delivery then rescheduled
        o4 = self._order(c['builders'], a['builders_site'], [('rebar', 3)], -22, -14)
        s4 = self._shipment(o4)
        t4 = self._trip(v['v2'], d['yousef'], s4, -22, -12, 'Amman - Sahab')
        t4.action_start()
        s4.write({'failure_reason': 'Construction site closed - no authorized receiver on site.'})
        s4.action_fail()
        t4.odometer_end = t4.odometer_start + 48
        t4.action_done()
        s4.action_retry()                                      # back to draft, ready for a new trip

        # 2) IN TRANSIT now
        o2 = self._order(c['noor'], a['noor_irbid'], [('water', 300)], -2, 5,
                         contract=self.contracts['noor'], priority='urgent')
        s2 = self._shipment(o2)
        t2 = self._trip(v['v1'], d['khaled'], s2, -1, 7, 'Amman - Irbid')
        t2.action_start()
        env['nexora.shipment.event'].create({
            'shipment_id': s2.id, 'event_type': 'checkpoint', 'location': 'Jerash Checkpoint',
            'note': 'Passed checkpoint, on schedule.'})

        # 3) PLANNED for tomorrow - pharma on the chilled van
        o3 = self._order(c['petra'], a['petra_zarqa'], [('pharma', 80)], 16, 22,
                         contract=self.contracts['petra'])
        s3 = self._shipment(o3)
        self._trip(v['v3'], d['omar'], s3, 16, 24, 'Amman - Zarqa')

        # 6) confirmed, nothing shipped yet (hazardous + heavy: try V1 vs V2)
        self._order(c['aqaba'], a['aqaba_plant'], [('solvent', 20), ('rebar', 2)], 30, 48,
                    contract=self.contracts['aqaba'])
        # 7) draft order
        self._order(c['cosmetics'], a['cosm_amman'], [('cosm', 100)], 40, 60, confirm=False)
        # 8) shipment created, no trip yet (chilled, exactly the van payload)
        o8 = self._order(c['fresh'], a['fresh_aqaba'], [('yogurt', 100)], 20, 30,
                         contract=self.contracts['fresh'], priority='urgent')
        self._shipment(o8)

    # ----------------------------------------------------------- procurement
    def _receive(self, po, done_when, ratio=1.0):
        for picking in po.picking_ids.filtered(lambda p: p.state not in ('done', 'cancel')):
            for move in picking.move_ids:
                move.quantity = move.product_uom_qty * ratio
                move.picked = True
            picking.with_context(skip_backorder=True, skip_sms=True).button_validate()
            picking.write({'date_done': done_when})

    def procurement(self):
        env = self.env
        Rule, PR, Tender = (env['nexora.purchase.approval.rule'], env['nexora.purchase.request'],
                            env['nexora.rfq.tender'])
        Rule.create({'name': 'Manager approval (500+)', 'min_amount': 500, 'approver_id': self.admin.id})
        Rule.create({'name': 'Director approval (5000+)', 'min_amount': 5000, 'approver_id': self.admin.id})

        def pr(reason, lines, prio='normal', due=7):
            return PR.create({
                'requester_id': self.admin.id, 'warehouse_id': self.wh_main.id,
                'cost_center_id': self.cc['fl'].id, 'date_required': self.days(due),
                'priority': prio, 'reason': reason,
                'line_ids': [Command.create({
                    'product_id': self.pv(k).id, 'name': self.prod[k].name, 'quantity': q,
                    'uom_id': self.prod[k].uom_id.id, 'estimated_price': price})
                    for k, q, price in lines]})

        pr('Spare wheels for the pickup (left in draft)', [('tire', 4, 215)])

        pr2 = pr('Heavy brake pads and oil for the Actros', [('brake', 6, 140), ('oil', 10, 46)],
                 prio='urgent', due=3)
        pr2.action_submit()                                             # waits for approval

        # open tender with three quotations to compare
        pr3 = pr('Engine oil stock for Q4 maintenance', [('oil', 30, 46)], due=10)
        pr3.action_submit()
        pr3.action_approve()
        t3 = Tender._create_from_request(
            pr3, self.vend['oil'] | self.vend['tires'] | self.vend['pack'], self.days(5))
        quotes = {self.vend['oil'].id: (44.0, 2), self.vend['tires'].id: (47.5, 5),
                  self.vend['pack'].id: (51.0, 9)}
        for po in t3.quote_ids:
            price, delay = quotes[po.partner_id.id]
            po.order_line.write({'price_unit': price, 'date_planned': self.hours(24 * delay)})

        # auto-approved request, tender awarded and goods received on time
        pr4 = pr('Stretch wrap for outbound pallets', [('wrap', 100, 4)])
        pr4.action_submit()
        t4 = Tender._create_from_request(pr4, self.vend['pack'] | self.vend['oil'], self.days(3))
        for po in t4.quote_ids:
            po.order_line.write({
                'price_unit': 3.9 if po.partner_id == self.vend['pack'] else 4.4,
                'date_planned': self.hours(-8 * 24)})
        winner = t4.quote_ids.filtered(lambda p: p.partner_id == self.vend['pack'])
        winner.button_confirm()                                         # award: other RFQ is cancelled
        self._receive(winner, self.hours(-8 * 24), 1.0)

        pr5 = pr('Bulk pallet restock', [('pallet', 500, 11)])
        pr5.action_submit()
        pr5.reject_reason = 'Existing pallet stock is sufficient for the next quarter.'
        pr5.action_reject()

        # extra purchase orders so vendor performance has data
        def po(vendor, lines, planned_days):
            return env['purchase.order'].create({
                'partner_id': vendor.id,
                'order_line': [Command.create({
                    'product_id': self.pv(k).id, 'name': self.prod[k].name, 'product_qty': q,
                    'price_unit': price, 'date_planned': self.hours(planned_days * 24)})
                    for k, q, price in lines]})

        po_a = po(self.vend['tires'], [('tire', 8, 208)], -10)
        po_a.button_confirm()
        self._receive(po_a, self.hours(-11 * 24), 1.0)                  # early

        po_b = po(self.vend['oil'], [('oil', 30, 45)], -10)
        po_b.button_confirm()
        self._receive(po_b, self.hours(-6 * 24), 0.8)                   # late and partial

        po_c = po(self.vend['pallets'], [('pallet', 100, 11)], -5)
        po_c.button_confirm()
        self._receive(po_c, self.hours(-5 * 24), 1.0)                   # on time

        env['nexora.vendor.performance']._compute_all(days=90)