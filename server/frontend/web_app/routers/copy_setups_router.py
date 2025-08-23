from __future__ import annotations

from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, Request, Form, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import insert

from frontend.web_app.utils import templates, get_current_user, inject_common_context
from backend.db.functions import get_session, AsyncSession
from backend.db.crud.general import read, create
from backend.db.crud.copy_setup import get_copy_setups_on_user_id
from backend.db.crud.copy_setup_config import get_copy_setup_configs_on_user_id
from auth.csrf import generate_csrf_token, validate_csrf
from auth.tokens import generate_cs_token
from models import User, CopySetup, CopySetupConfig, TgChat
from model_links import CopySetupTgChatLink
from enums import LotMode, MultipleTPMode, MultipleEntryMode, TgChatType, UserRole


router = APIRouter(prefix="", include_in_schema=False)


async def cleaned_form(request: Request) -> Dict[str, Any]:
    form = await request.form()
    # Convert empty strings to None to handle optional fields gracefully
    return {k: (form.get(k, None) or None if not k.endswith("[]") else form.getlist(k)) for k in form.keys()}


@router.get("/copy_setups", response_class=HTMLResponse)
async def copy_setups_page(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    setups = await get_copy_setups_on_user_id(db, user.id)
    configs = await get_copy_setup_configs_on_user_id(db, user.id)
    ctx = {
        **inject_common_context(request, user),
        "csrf_token": generate_csrf_token(request),
        "setups": setups,
        "configs": configs,
        "tg_chats": [
            chat for chat in ((await read(TgChat, db)) or []) 
            if (user.role == UserRole.ADMIN) or (chat.chat_type in 
            [TgChatType.SUPER_GROUP, TgChatType.CHANNEL])
        ],
    }
    return templates.TemplateResponse("copy_setups.html", ctx)


@router.post("/copy_setups/create_config")
async def create_config_action(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
    form_data: Dict[str, Any] = Depends(cleaned_form),
):
    try:
        csrf_token = form_data.get("csrf_token")
        validate_csrf(request, csrf_token)
    except ValueError:
        return HTMLResponse("Invalid CSRF", status_code=status.HTTP_400_BAD_REQUEST)
    print(form_data)
    # Extract and clean form fields from the form_data
    name = form_data.get("name")
    allowed_symbols = form_data.get("allowed_symbols")
    symbols = form_data.get("symbols") or []
    synonyms = form_data.get("synonyms") or []

    lot_mode = form_data.get("lot_mode") or "AUTO"
    fixed_lot = form_data.get("fixed_lot")
    max_risk_perc_from_equity_per_signal = form_data.get("max_risk_perc_from_equity_per_signal") or 0 
    max_price_range_perc = form_data.get("max_price_range_perc")
    multiple_tp_mode = form_data.get("multiple_tp_mode") or "ALL"
    multiple_entry_mode = form_data.get("multiple_entry_mode") or "ALL"

    # Booleans: form sends "on" if checked, else None or don't include
    close_on_signal_reply = form_data.get("close_on_signal_reply") == "on"
    modify_on_signal_reply = form_data.get("modify_on_signal_reply") == "on"
    close_on_msg_delete = form_data.get("close_on_msg_delete") == "on"
    ignore_prices_out_of_range = form_data.get("ignore_prices_out_of_range") != "off"

    breakeven_on_tp_layer = form_data.get("breakeven_on_tp_layer")
    close_trades_before_everyday_swap = form_data.get("close_trades_before_everyday_swap") == "on"
    close_trades_before_wednesday_swap = form_data.get("close_trades_before_wednesday_swap") == "on"
    close_trades_before_weekend = form_data.get("close_trades_before_weekend") == "on"
    trailingstop_on_tps = form_data.get("trailingstop_on_tps") == "on"

    tradeprofit_percent_from_balans_for_breakeven = form_data.get("tradeprofit_percent_from_balans_for_breakeven")

    expire_minutes_pending_trade = form_data.get("expire_minutes_pending_trade")
    expire_minutes_active_trade = form_data.get("expire_minutes_active_trade")
    expire_at_tp_hit_before_entry = form_data.get("expire_at_tp_hit_before_entry")

    follow_tp_and_sl_hits_from_others = form_data.get("follow_tp_and_sl_hits_from_others") == "on"

    symbol_synonyms_mapping = {
        sym: syn.split(",") if syn else [] for sym, syn in zip(symbols, synonyms)
    }

    try:
        copy_setup_config = await create(
            CopySetupConfig(
                user_id=user.id,
                name=name,
                allowed_symbols=allowed_symbols,
                symbol_synonyms_mapping=symbol_synonyms_mapping,
                lot_mode=LotMode(lot_mode),  # Assuming conversion like before, be careful!
                fixed_lot=fixed_lot if fixed_lot is None else float(fixed_lot),
                max_price_range_perc=max_price_range_perc if max_price_range_perc is None else float(max_price_range_perc),
                max_risk_perc_from_equity_per_signal=max_risk_perc_from_equity_per_signal,
                multiple_tp_mode=MultipleTPMode(multiple_tp_mode),
                multiple_entry_mode=MultipleEntryMode(multiple_entry_mode),
                close_on_signal_reply=close_on_signal_reply,
                modify_on_signal_reply=modify_on_signal_reply,
                close_on_msg_delete=close_on_msg_delete,
                ignore_prices_out_of_range=ignore_prices_out_of_range,
                breakeven_on_tp_layer=None if breakeven_on_tp_layer is None else int(breakeven_on_tp_layer),
                close_trades_before_everyday_swap=close_trades_before_everyday_swap,
                close_trades_before_wednesday_swap=close_trades_before_wednesday_swap,
                close_trades_before_weekend=close_trades_before_weekend,
                trailingstop_on_tps=trailingstop_on_tps,
                tradeprofit_percent_from_balans_for_breakeven=(
                    None if tradeprofit_percent_from_balans_for_breakeven is None else float(tradeprofit_percent_from_balans_for_breakeven)
                ),
                expire_minutes_pending_trade=None if expire_minutes_pending_trade is None else int(expire_minutes_pending_trade),
                expire_minutes_active_trade=None if expire_minutes_active_trade is None else int(expire_minutes_active_trade),
                expire_at_tp_hit_before_entry=None if expire_at_tp_hit_before_entry is None else int(expire_at_tp_hit_before_entry),
                follow_tp_and_sl_hits_from_others=follow_tp_and_sl_hits_from_others
            ),
            db,
        )
    except ValueError as e:
        await db.rollback()
        return HTMLResponse(str(e), status_code=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        await db.rollback()
        return HTMLResponse(f"Failed to create config: {e}", status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)

    return RedirectResponse(url="/copy_setups", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/copy_setups/create_setup")
async def create_setup_action(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
    form_data: Dict[str, Any] = Depends(cleaned_form),
):
    try:
        csrf_token = form_data.get("csrf_token")
        validate_csrf(request, csrf_token)
    except ValueError:
        return HTMLResponse("Invalid CSRF", status_code=status.HTTP_400_BAD_REQUEST)

    try:
        print(form_data)
        config_id = int(form_data.get("config_id"))
        tg_chats = form_data.get("tg_chats[]") or []
        # Convert list of tg_chats IDs if needed (they may come as strings)
        tg_chats = [int(t) for t in tg_chats] if tg_chats else []
        print("tg_chats:", tg_chats)
        copy_setup = await create(
            CopySetup(
                user_id=user.id,
                config_id=config_id,
                cs_token=generate_cs_token()
            ),
            db
        )

        # Link Telegram chats
        stmt = insert(CopySetupTgChatLink)
        values = [{"copy_setup_id": copy_setup.id, "tg_chat_id": chat_id} for chat_id in tg_chats]
        await db.execute(stmt, values)
    except ValueError as e:
        await db.rollback()
        return HTMLResponse(str(e), status_code=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        await db.rollback()
        return HTMLResponse(f"Failed to create setup: {e}", status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)

    return RedirectResponse(url=f"/copy_setup/{copy_setup.id}", status_code=status.HTTP_303_SEE_OTHER)


from sqlalchemy import select
from sqlalchemy.orm import selectinload

@router.get("/copy_setup/{setup_id}", response_class=HTMLResponse)
async def copy_setup_detail_page(
    setup_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    # Fetch the setup with its config and related tg_chats
    result = await db.execute(
        select(CopySetup)
        .where(CopySetup.id == setup_id, CopySetup.user_id == user.id)
        .options(
            selectinload(CopySetup.config),
            selectinload(CopySetup.tg_chats)
        )
    )
    setup: CopySetup | None = result.scalars().first()

    if not setup:
        return HTMLResponse("Not found", status_code=404)

    ctx = {
        **inject_common_context(request, user),
        "setup": setup,
    }
    return templates.TemplateResponse("copy_setup_detail.html", ctx)
