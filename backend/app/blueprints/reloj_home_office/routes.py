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


# JSON API: snapshot and mark endpoints
@bp.get('/api/snapshot')
@login_required
@view_required('reloj_home_office')
def api_snapshot():
    """Return the current clock snapshot for the logged‑in user.

    This endpoint wraps ``get_user_clock_snapshot`` and exposes its
    return value as JSON.  It avoids rendering HTML and can be
    consumed by the React frontend to display the home office clock
    status without page reloads.
    """
    from flask import jsonify
    snapshot = get_user_clock_snapshot(current_user)
    return jsonify(snapshot)


@bp.post('/api/marcar')
@login_required
@view_required('reloj_home_office')
def api_marcar():
    """Queue a new home office mark for the logged‑in user.

    This endpoint proxies to ``queue_home_office_mark`` and returns
    a JSON object with keys ``ok`` (boolean) and ``msg`` (string)
    describing the result.  It does not redirect so it can be used
    from the React frontend.  A ``200`` status with ``ok`` set to
    ``False`` indicates an application-level error (for example,
    the user is not enabled or there is a configuration issue).
    """
    from flask import jsonify
    ok, msg = queue_home_office_mark(current_user)
    return jsonify({"ok": ok, "msg": msg})


@bp.post('/marcar')
@login_required
@view_required('reloj_home_office')
def marcar():
    ok, msg = queue_home_office_mark(current_user)
    flash(msg, 'info' if ok else 'error')
    return redirect(url_for('reloj_home_office.index'))
