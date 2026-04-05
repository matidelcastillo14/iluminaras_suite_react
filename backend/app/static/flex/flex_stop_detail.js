(function(){
  const stopId = window.FLEX_STOP_ID;
  const btnArriving = document.getElementById('btnArriving');
  const dlg = document.getElementById('dlgAction');
  const dlgTitle = document.getElementById('dlgTitle');
  const fShipmentId = document.getElementById('fShipmentId');
  const fAction = document.getElementById('fAction');
  const fNote = document.getElementById('fNote');
  const fPhoto = document.getElementById('fPhoto');

  const returnToWrap = document.getElementById('returnToWrap');
  const fReturnTo = document.getElementById('fReturnTo');

  // NUEVO: receptor (entregado)
  const receiverWrap = document.getElementById('receiverWrap');
  const fReceiverRel = document.getElementById('fReceiverRelation');
  const fReceiverName = document.getElementById('fReceiverName');
  const fReceiverId = document.getElementById('fReceiverId');

  const dlgErr = document.getElementById('dlgErr');
  const btnConfirm = document.getElementById('btnConfirm');
  const actionForm = document.getElementById('actionForm');

  function showErr(msg){
    dlgErr.style.display='block';
    dlgErr.textContent = msg;
  }
  function hideErr(){
    dlgErr.style.display='none';
    dlgErr.textContent='';
  }

  function setReceiverVisible(isVisible){
    if(!receiverWrap) return;

    receiverWrap.style.display = isVisible ? 'block' : 'none';

    // Importante: required dinámico (si queda required cuando está oculto, bloquea otras acciones)
    if(fReceiverRel)  fReceiverRel.required  = !!isVisible;
    if(fReceiverName) fReceiverName.required = !!isVisible;
    if(fReceiverId)   fReceiverId.required   = !!isVisible;

    if(!isVisible){
      if(fReceiverRel)  fReceiverRel.value = '';
      if(fReceiverName) fReceiverName.value = '';
      if(fReceiverId)   fReceiverId.value = '';
    }
  }

  function setReturnToVisible(isVisible){
    if(!returnToWrap) return;
    returnToWrap.style.display = isVisible ? 'block' : 'none';
    if(!isVisible && fReturnTo) fReturnTo.value = '';
  }

  if(btnArriving){
    btnArriving.addEventListener('click', async (ev)=>{
      ev.preventDefault();
      try{
        await window.FlexApi.stopArriving(stopId);
        btnArriving.textContent='Listo';
        btnArriving.disabled = true;
      }catch(e){
        alert('No se pudo marcar llegando: ' + e.message);
      }
    });
  }

  document.querySelectorAll('.fx-shipment .act').forEach(btn => {
    btn.addEventListener('click', (ev)=>{
      ev.preventDefault();
      const card = btn.closest('.fx-shipment');
      const sid = card.getAttribute('data-shipment-id');
      const act = btn.getAttribute('data-action');

      hideErr();

      if(fShipmentId) fShipmentId.value = sid;
      if(fAction) fAction.value = act;
      if(fNote) fNote.value = '';
      if(fPhoto) fPhoto.value = '';

      dlgTitle.textContent =
        (act === 'DELIVERED') ? 'Entregado' :
        (act === 'DELIVERY_FAILED') ? 'No entregado' :
        (act === 'OUT_FOR_DELIVERY') ? 'Reintentar entrega' :
        (act === 'DEFERRED_NEXT_SHIFT') ? 'Siguiente turno' :
        (act === 'RETURN_TO_DEPOT_REQUESTED') ? 'Devolver a depósito' :
        'Acción';

      // Mostrar/ocultar UI según acción
      setReturnToVisible(act === 'RETURN_TO_DEPOT_REQUESTED');
      setReceiverVisible(act === 'DELIVERED');

      dlg.showModal();
    });
  });

  if(btnConfirm){
    btnConfirm.addEventListener('click', async (ev)=>{
      ev.preventDefault();
      hideErr();
      btnConfirm.disabled = true;

      try{
        const fd = new FormData(actionForm);
        const act = (fd.get('action') || '').toString();

        // Validaciones
        if(act === 'DELIVERED'){
          const rel = (fd.get('receiver_relation') || '').toString().trim();
          const name = (fd.get('receiver_name') || '').toString().trim();
          const doc = (fd.get('receiver_id') || '').toString().trim();
          if(!rel || !name || !doc){
            showErr('Para marcar ENTREGADO tenés que completar: relación, nombre y documento.');
            btnConfirm.disabled = false;
            return;
          }
        }

        if(act === 'RETURN_TO_DEPOT_REQUESTED'){
          const rto = (fd.get('return_to_user_id') || '').toString().trim();
          if(!rto){
            showErr('Tenés que seleccionar a quién se lo devolvés en depósito.');
            btnConfirm.disabled = false;
            return;
          }
        }

        await window.FlexApi.shipmentAction(fd);

        dlg.close();
        window.location.reload();
      }catch(e){
        showErr(e.message || 'Error inesperado');
      }finally{
        btnConfirm.disabled = false;
      }
    });
  }
})();
