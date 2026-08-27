import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.schemas.pix_key import PixKeyCreateRequest, PixKeyCreateResponse
from app.services.pix_key_service import create_pix_key, delete_pix_key

router = APIRouter(prefix="/v1/pix-keys", tags=["pix-keys"])


@router.post("", status_code=status.HTTP_201_CREATED, response_model=PixKeyCreateResponse)
def post_pix_key(payload: PixKeyCreateRequest, db: Session = Depends(get_db)) -> PixKeyCreateResponse:
    pix_key = create_pix_key(db, payload)
    return PixKeyCreateResponse(id=pix_key.id, tipo=pix_key.tipo, valor=pix_key.valor, created_at=pix_key.created_at)


@router.delete("/{pix_key_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_pix_key_endpoint(pix_key_id: uuid.UUID, db: Session = Depends(get_db)) -> None:
    delete_pix_key(db, pix_key_id)
