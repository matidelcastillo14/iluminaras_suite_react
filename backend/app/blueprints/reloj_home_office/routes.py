from __future__ import annotations

from flask import flash, redirect, render_template, url_for
from flask_login import current_user, login_required

from ...services.home_office_clock import get_user_clock_snapshot, queue_home_office_mark
from ...utils import view_required
from . import bp


@bp.get('/')
@login_required
@view_required('reloj_home_office')
def index():
    snapshot = get_user_clock_snapshot(current_user)
    return render_template('reloj_home_office/index.html', snapshot=snapshot)


@bp.post('/marcar')
@login_required
@view_required('reloj_home_office')
def marcar():
    ok, msg = queue_home_office_mark(current_user)
    flash(msg, 'info' if ok else 'error')
    return redirect(url_for('reloj_home_office.index'))
