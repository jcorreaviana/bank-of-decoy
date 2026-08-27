import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.schemas.pix_key import PixKeyCreateRequest, PixKeyCreateResponse, PixKeyLookupResponse
from app.services.pix_key_service import create_pix_key, delete_pix_key, lookup_pix_key_by_valor

router = APIRouter(prefix="/v1/pix-keys", tags=["pix-keys"])


@router.post("", status_code=status.HTTP_201_CREATED, response_model=PixKeyCreateResponse)
def post_pix_key(payload: PixKeyCreateRequest, db: Session = Depends(get_db)) -> PixKeyCreateResponse:
    pix_key = create_pix_key(db, payload)
    return PixKeyCreateResponse(id=pix_key.id, tipo=pix_key.tipo, valor=pix_key.valor, created_at=pix_key.created_at)


@router.get("/lookup", response_model=PixKeyLookupResponse)
def get_pix_key_lookup(valor: str, db: Session = Depends(get_db)) -> PixKeyLookupResponse:
    """Consultada pelo transaction-service para validar pix_key_destino
    antes de criar uma transacao (specs/business/15-validacao-chave-destino.md).
    Inclui chaves soft-deleted (`ativa: false`) para o chamador distinguir
    'nao existe' (404) de 'existe mas foi cancelada' (200, ativa=false)."""
    pix_key = lookup_pix_key_by_valor(db, valor)
    return PixKeyLookupResponse(
        id=pix_key.id,
        account_id=pix_key.account_id,
        tipo=pix_key.tipo,
        valor=pix_key.valor,
        ativa=pix_key.deleted_at is None,
    )


@router.delete("/{pix_key_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_pix_key_endpoint(pix_key_id: uuid.UUID, db: Session = Depends(get_db)) -> None:
    delete_pix_key(db, pix_key_id)
