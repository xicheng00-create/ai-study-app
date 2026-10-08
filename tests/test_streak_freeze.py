from datetime import timedelta
from data import checkin, models, timeutil


def setup_user(con):
    row = con.execute("SELECT id FROM users WHERE role='student' LIMIT 1").fetchone()
    if row:
        return row['id']
    uid = models.new_id()
    con.execute("INSERT INTO users(id,username,password_hash,role,is_active,created_at) VALUES(?,?,?,'student',1,?)",
                (uid, 'freeze_test', 'x', models.utcnow()))
    con.commit()
    return uid


def add_day(con, uid, d, streak):
    con.execute("INSERT INTO daily_checkins(id,user_id,checkin_date,streak_after,created_at) VALUES(?,?,?,?,?)",
                (models.new_id(), uid, d, streak, models.utcnow()))
    con.commit()


def test_initial_balance(client):
    with client.application.app_context():
        from data.db import get_db
        assert checkin.freeze_status(get_db(), setup_user(get_db()))['available'] == 2


def test_milestone_balance(client):
    with client.application.app_context():
        from data.db import get_db
        con=get_db(); uid=setup_user(con); d=(timeutil.shanghai_now().date()-timedelta(days=8)).isoformat()
        add_day(con,uid,d,5); add_day(con,uid,(timeutil.shanghai_now().date()-timedelta(days=7)).isoformat(),10)
        assert checkin.freeze_status(con,uid)['granted']==4


def test_gap_one_consumed_once_and_preserves_streak(client, monkeypatch):
    with client.application.app_context():
        from data.db import get_db
        con=get_db(); uid=setup_user(con); last=timeutil.shanghai_now().date()-timedelta(days=2)
        add_day(con,uid,last.isoformat(),11)
        result=checkin.settle_freezes(con,uid)
        assert result['consumed']==[(last+timedelta(days=1)).isoformat()]
        assert checkin.streak_info(con,uid)['streak']==11
        checkin.settle_freezes(con,uid)
        assert con.execute('SELECT COUNT(*) FROM streak_freezes WHERE user_id=?',(uid,)).fetchone()[0]==1


def test_no_balance_gap_one_not_recorded(client):
    _assert_uncovered(client, 2, used=2)


def test_gap_three_with_two_balance_not_partially_recorded(client):
    # 余额 2、缺口 3 天 → 部分覆盖不算保住：一行都不许写（used=0 才是「可用 2」）
    _assert_uncovered(client, 4, used=0)


def test_frozen_streak_uses_last_run_not_longest(client):
    """被冰冻保住的数字 = 最后一次打卡行的 streak_after，不是历史最大值 longest。"""
    with client.application.app_context():
        from data.db import get_db
        con = get_db(); uid = setup_user(con); today = timeutil.shanghai_now().date()
        add_day(con, uid, (today - timedelta(days=30)).isoformat(), 20)   # 历史长跑
        add_day(con, uid, (today - timedelta(days=4)).isoformat(), 1)     # 当前短跑
        add_day(con, uid, (today - timedelta(days=3)).isoformat(), 2)
        add_day(con, uid, (today - timedelta(days=2)).isoformat(), 3)
        assert checkin.settle_freezes(con, uid)['consumed'] == [(today - timedelta(days=1)).isoformat()]
        info = checkin.streak_info(con, uid)
        assert info['streak'] == 3          # 不是 longest=20
        assert info['longest'] == 20
        assert info['freezes']['records'][0] == {'freeze_date': (today - timedelta(days=1)).isoformat(),
                                                'streak_kept': 3}


def test_balance_floor_zero(client):
    with client.application.app_context():
        from data.db import get_db
        con=get_db();uid=setup_user(con)
        for i in range(3):
            con.execute('INSERT INTO streak_freezes VALUES(?,?,?,?,?)',(models.new_id(),uid,f'2020-01-0{i+1}',0,models.utcnow()))
        con.commit();assert checkin.freeze_status(con,uid)['available']==0


def _assert_uncovered(client, days, used):
    with client.application.app_context():
        from data.db import get_db
        con=get_db();uid=setup_user(con);last=timeutil.shanghai_now().date()-timedelta(days=days)
        add_day(con,uid,last.isoformat(),11)
        for i in range(used):
            con.execute('INSERT INTO streak_freezes VALUES(?,?,?,?,?)',(models.new_id(),uid,f'2020-01-0{i+1}',11,models.utcnow()))
        con.commit(); checkin.settle_freezes(con,uid)
        info=checkin.streak_info(con,uid)
        assert info['streak']==0
        assert con.execute('SELECT COUNT(*) FROM streak_freezes WHERE user_id=?',(uid,)).fetchone()[0]==used
