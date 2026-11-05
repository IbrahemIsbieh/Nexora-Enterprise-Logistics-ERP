"""JSON representations shared by the REST API and the webhook payloads."""


def iso(value):
    if not value:
        return None
    if hasattr(value, 'hour'):                       # datetime (naive, UTC)
        return value.replace(microsecond=0).isoformat() + 'Z'
    return value.isoformat()                         # date


def customer_ref(partner):
    p = partner.sudo()
    if not p:
        return None
    return {'id': p.id, 'code': p.nexora_code or None, 'name': p.name}


def address(partner):
    p = partner.sudo()
    if not p:
        return None
    return {'id': p.id, 'name': p.name, 'street': p.street or None,
            'city': p.city or None, 'phone': p.phone or None}


def cargo_line(line):
    return {
        'description': line.name, 'quantity': line.quantity,
        'weight_kg': line.weight, 'volume_m3': line.volume,
        'temperature_class': line.temperature_class, 'hazardous': line.hazardous,
    }


def event(ev):
    return {'id': ev.id, 'date': iso(ev.date), 'type': ev.event_type,
            'location': ev.location or None, 'note': ev.note or None}


def shipment(s, internal=True):
    data = {
        'id': s.id,
        'number': s.name,
        'order': {'id': s.order_id.id, 'number': s.order_id.name,
                  'reference': s.order_id.reference or None},
        'customer': customer_ref(s.partner_id),
        'state': s.state,
        'trip': s.trip_id.name or None,
        'vehicle': s.vehicle_id.license_plate or None,
        'pickup_address': address(s.pickup_partner_id),
        'delivery_address': address(s.delivery_partner_id),
        'planned_pickup': iso(s.planned_pickup_date),
        'planned_delivery': iso(s.planned_delivery_date),
        'actual_pickup': iso(s.actual_pickup_date),
        'actual_delivery': iso(s.actual_delivery_date),
        'weight_kg': s.total_weight,
        'volume_m3': s.total_volume,
        'temperature_class': s.temperature_class,
        'hazardous': s.has_hazardous,
        'on_time': s.on_time if s.state == 'delivered' else None,
        'delay_hours': s.delay_hours if s.state == 'delivered' else None,
        'failure_reason': s.failure_reason or None,
        'received_by': s.pod_receiver_name or None,
        'lines': [cargo_line(line) for line in s.line_ids],
    }
    if internal:
        data['driver'] = s.driver_id.name or None
    return data


def order(o, internal=True):
    return {
        'id': o.id,
        'number': o.name,
        'reference': o.reference or None,
        'state': o.state,
        'priority': o.priority,
        'customer': customer_ref(o.partner_id),
        'pickup_address': address(o.pickup_partner_id),
        'delivery_address': address(o.delivery_partner_id),
        'requested_pickup': iso(o.requested_pickup_date),
        'requested_delivery': iso(o.requested_delivery_date),
        'weight_kg': o.total_weight,
        'volume_m3': o.total_volume,
        'temperature_class': o.temperature_class,
        'hazardous': o.has_hazardous,
        'notes': o.notes or None,
        'lines': [cargo_line(line) for line in o.line_ids],
        'shipments': [{'id': s.id, 'number': s.name, 'state': s.state}
                      for s in o.shipment_ids if s.state != 'cancelled'],
    }


def trip(t, internal=True):
    data = {
        'id': t.id,
        'number': t.name,
        'state': t.state,
        'vehicle': t.vehicle_id.license_plate or None,
        'route': t.route or None,
        'planned_start': iso(t.planned_start),
        'planned_end': iso(t.planned_end),
        'actual_start': iso(t.actual_start),
        'actual_end': iso(t.actual_end),
        'distance_km': t.distance,
        'shipments': [s.name for s in t.shipment_ids if s.state != 'cancelled'],
    }
    if internal:
        data['driver'] = t.driver_id.name or None
    return data


def vehicle(v, internal=True):
    data = {
        'id': v.id,
        'plate': v.license_plate,
        'model': v.model_id.display_name or None,
        'class': v.nexora_vehicle_class or None,
        'availability': v.nexora_availability,
        'odometer_km': v.odometer,
        'max_payload_kg': v.nexora_max_payload,
        'cargo_volume_m3': v.nexora_cargo_volume,
        'temperature_capability': v.nexora_temperature_class,
        'hazmat_certified': v.nexora_hazmat_certified,
    }
    if internal:
        data['current_driver'] = v.nexora_current_driver_id.name or None
    return data


def customer(p):
    return {'id': p.id, 'code': p.nexora_code or None, 'name': p.name,
            'city': p.city or None, 'phone': p.phone or None, 'email': p.email or None}


def serialize(record, internal=True):
    func = {
        'nexora.shipment': shipment,
        'nexora.transport.order': order,
        'nexora.transport.trip': trip,
    }[record._name]
    return func(record, internal=internal)