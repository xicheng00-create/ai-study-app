"""Atomic creation shared by manual, batch and daily prewarm callers."""
from data import models


def enqueue(con, card_id, requested_by=None):
    con.execute("""INSERT INTO card_videos
        (id,core_card_id,chapter_id,status,title,requested_by,requested_at)
        SELECT ?,id,chapter_id,'queued',front,?,? FROM knowledge_cards WHERE id=?
        ON CONFLICT(core_card_id) DO UPDATE SET
          status='queued',error=NULL,requested_by=excluded.requested_by,
          requested_at=excluded.requested_at
        WHERE card_videos.status='failed'""",
        (models.new_id(), requested_by, models.utcnow(), card_id))
    return con.execute('SELECT * FROM card_videos WHERE core_card_id=?', (card_id,)).fetchone()
