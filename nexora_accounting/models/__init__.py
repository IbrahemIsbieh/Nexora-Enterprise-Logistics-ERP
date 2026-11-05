from . import freight_rate
from . import res_config_settings
from . import shipment
from . import trip
from . import expense
from . import account_move
from . import purchase_order
# The SQL report must stay last: its view reads columns added by the models above.
from . import cost_center_report