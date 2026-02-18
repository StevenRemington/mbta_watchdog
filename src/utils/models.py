from dataclasses import dataclass
from datetime import datetime

@dataclass
class TrainStatus:
    train_id: str
    status: str
    delay_minutes: int
    station: str
    direction: str
    log_time: datetime

    @property
    def is_late(self):
        return self.delay_minutes > 5 or self.status == "CANCELED"