from sqlalchemy import Column, Integer, String, DateTime
from datetime import datetime
from database import Base

class SearchHistory(Base):
    __tablename__ = "search_history"

    id = Column(Integer, primary_key=True, index=True)
    city = Column(String, index=True)
    units = Column(String, default="metric")
    endpoint = Column(String)
    result = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)


