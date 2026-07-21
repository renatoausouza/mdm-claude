export type Lang = 'en' | 'pt'

export const SUPPORTED_LANGUAGES: Lang[] = ['en', 'pt']
export const LANGUAGE_STORAGE_KEY = 'mdm.language'

// Server-side default when no language signal exists at all; matches
// src/mdm/i18n.py's own DEFAULT_LANGUAGE, kept independent of this file's
// browser-detected default below (see LanguageContext.tsx).
export const FALLBACK_LANGUAGE: Lang = 'pt'

// Flat, dot-namespaced keys — same shape as the backend's mdm.i18n.MESSAGES
// dict, deliberately not a nested object: a flat lookup keeps t() trivial
// (no path-walking) and keeps every key greppable as a single string.
export const translations: Record<Lang, Record<string, string>> = {
  en: {
    // ---- common ----
    'common.loading': 'Loading…',
    'common.none': '—',
    'common.yes': 'Yes',
    'common.job': 'Job',
    'common.case': 'Case',
    'common.editRequest': 'Edit request',
    'common.statusUpdateMessage': '{subject} is now {status}.',

    // ---- layout / nav ----
    'layout.brandCaption': 'Master Data Registry',
    'layout.pageTitle': 'MDM — Master Data Registry',
    'layout.navIntake': 'Intake',
    'layout.navDashboard': 'Dashboard',
    'layout.navQueuesSection': 'Queues',
    'layout.navMasterDataSection': 'Master Data',
    'layout.navRecordsSection': 'Records',
    'layout.navAuditLog': 'Audit log',
    'layout.navHelp': 'Help',
    'layout.logout': 'Log out',
    'layout.languageToggleLabel': 'Language',

    // ---- login page ----
    'login.title': 'Sign in',
    'login.username': 'Username',
    'login.password': 'Password',
    'login.authenticatorCode': 'Authenticator code',
    'login.authenticatorHint': ' (approver accounts only, once enrolled)',
    'login.submitting': 'Signing in…',
    'login.submit': 'Sign in',

    // ---- MFA enrollment page ----
    'mfaEnroll.doneTitle': 'Two-factor authentication enabled',
    'mfaEnroll.doneBody': 'Sign in again with your username, password, and a current authenticator code.',
    'mfaEnroll.goToSignIn': 'Go to sign in',
    'mfaEnroll.title': 'Set up two-factor authentication',
    'mfaEnroll.introPrefix': 'Approver account ',
    'mfaEnroll.introSuffix': ' requires an authenticator app before it can be used.',
    'mfaEnroll.manualCodePrefix': 'Or enter this code manually: ',
    'mfaEnroll.codeLabel': 'Enter the 6-digit code from your authenticator app',
    'mfaEnroll.verifying': 'Verifying…',
    'mfaEnroll.confirm': 'Confirm',

    // ---- home page ----
    'home.welcome': 'Welcome',
    'home.intro': 'Master data registration — upload a document, then review candidates in the queues below.',
    'home.uploadLink': 'Upload a document',
    'home.queueLink': '{domain} review queue',
    'home.helpLink': 'How this works',

    // ---- upload page ----
    'upload.title': 'Upload a document',
    'upload.intro': 'Supplier, Client, and Product candidates are all extracted from a single upload.',
    'upload.file': 'File',
    'upload.submitting': 'Uploading and extracting…',
    'upload.submit': 'Upload',
    'upload.progressLabel': 'Extracting document — this can take a few minutes…',
    'upload.resultsTitle': 'Extraction results',
    'upload.colDomain': 'Domain',
    'upload.colStatus': 'Status',
    'upload.colDuplicate': 'Duplicate?',
    'upload.viewJob': 'View job',
    'upload.another': 'Upload another',

    // ---- queue page ----
    'queue.title': '{domain} review queue',
    'queue.filterNeedsReview': 'Needs review',
    'queue.filterNeedsInfo': 'Needs info',
    'queue.filterApproved': 'Approved',
    'queue.filterRejected': 'Rejected',
    'queue.filterAll': 'All',
    'queue.truncatedNotice':
      "Showing the most recent 200 matching jobs — older ones aren't shown. Narrow the status filter above to see more.",
    'queue.empty': 'No jobs match this filter.',
    'queue.colStatus': 'Status',
    'queue.colCreated': 'Created',
    'queue.colSubmittedBy': 'Submitted by',
    'queue.colDuplicate': 'Duplicate?',
    'queue.review': 'Review',

    // ---- master data (consult/search + detail) ----
    'masterData.title': '{domain} master data',
    'masterData.searchPlaceholder': 'Search by any field value…',
    'masterData.empty': 'No records match this filter.',
    'masterData.colKey': 'Key',
    'masterData.colPreview': 'Preview',
    'masterData.colVersion': 'Version',
    'masterData.view': 'View',
    'masterData.loadMore': 'Load more',
    'masterData.detailTitle': '{domain} record',
    'masterData.key': 'Key: {key}',
    'masterData.version': 'Version {version}',
    'masterData.firstRegistered': 'First registered: {date}',
    'masterData.lastUpdated': 'Last updated: {date}',
    'masterData.fieldsTitle': 'Fields',
    'masterData.edit': 'Edit',
    'masterData.save': 'Save',
    'masterData.cancel': 'Cancel',
    'masterData.editSuccess': 'Record updated.',
    'masterData.keyFieldReadOnlyHint': 'The key field cannot be edited here.',
    'masterData.proposeEdit': 'Propose edit',
    'masterData.proposeEditSubmit': 'Submit proposal',
    'masterData.pendingEditBanner': 'There is a pending edit request for this record.',
    'masterData.reviewEditRequest': 'Review edit request',
    'masterData.editRequestSubmitted': 'Edit request submitted — a different approver must review it.',

    // ---- edit request review page ----
    'editRequest.title': 'Edit request review',
    'editRequest.segregationBanner': 'You submitted this edit request — a different approver must review it.',
    'editRequest.segregationTitle': 'You cannot approve your own edit request',
    'editRequest.approverOnlyHint': 'Only approver accounts can review an edit request.',

    // ---- review detail page ----
    'review.candidateTitle': '{domain} candidate',
    'review.duplicateFoundBanner': 'A matching record was found for this candidate.',
    'review.resolveDuplicate': 'Resolve duplicate',
    'review.scoringTitle': 'Scoring',
    'review.scoringSummary': 'Reliability: {reliability} · Completeness: {completeness}% · Compliance: {compliance}%',
    'review.missingRequired': 'Missing required: {fields}',
    'review.lowConfidence': 'Low confidence: {fields}',
    'review.fieldsTitle': 'Extracted fields',
    'review.copyRawJson': 'Copy raw JSON',
    'review.evidenceTitle': 'Transactional evidence (not part of the registered record)',
    'review.partiesTitle': 'Tagged parties in this document',
    'review.inferredRole': ' (inferred from position, not a matched label — please verify)',
    'review.inferredRoleTitle': 'Guessed from document position — no label was found; double-check this one',
    'review.matchedRole': ' (matched "{label}")',
    'review.decisionTitle': 'Decision',
    'review.notes': 'Notes',
    'review.overridesHint': 'Assign a value for any field the candidate is missing before approving as new:',
    'review.segregationApproveBanner':
      'You submitted this {domain} candidate — segregation of duties means you cannot approve your own submission. Reject or request more info, or have another approver review it.',
    'review.segregationApproveTitle': 'You cannot approve your own submission for this domain',
    'review.approve': 'Approve',
    'review.reject': 'Reject',
    'review.requestInfo': 'Request info',
    'review.notesRequired': 'Notes are required when requesting more information.',
    'review.searchSummary': 'Search for an existing {domain} to link this candidate to',
    'review.searchPlaceholder': 'Search by any extracted field value…',
    'review.search': 'Search',
    'review.noMatches': 'No matches.',
    'review.link': 'Link',
    'review.approverOnlyHint': 'Only approver accounts can approve, reject, or request more information.',

    // ---- duplicate resolve page ----
    'duplicate.title': 'Duplicate review',
    'duplicate.matchedOnManual': 'manually linked by a reviewer',
    'duplicate.matchedOn': 'Matched on: {key}',
    'duplicate.colField': 'Field',
    'duplicate.colExisting': 'Existing value',
    'duplicate.colNew': 'New value',
    'duplicate.colAccept': 'Accept this field?',
    'duplicate.notes': 'Notes',
    'duplicate.segregationBanner':
      'You submitted this {domain} candidate — segregation of duties means you cannot accept an update to your own submission. You may still reject it, or have another approver resolve it.',
    'duplicate.segregationTitle': 'You cannot resolve a duplicate for your own submission',
    'duplicate.selectFieldTitle': 'Select at least one differing field above',
    'duplicate.acceptAll': 'Accept all',
    'duplicate.acceptSelected': 'Accept selected fields',
    'duplicate.acceptSelectedCount': 'Accept selected fields ({count} selected)',
    'duplicate.reject': 'Reject',
    'duplicate.approverOnlyHint': 'Only approver accounts can resolve a duplicate review case.',

    // ---- audit page ----
    'audit.title': 'Audit log',
    'audit.filterPlaceholder': 'Filter by document id…',
    'audit.filter': 'Filter',
    'audit.colWhen': 'When',
    'audit.colAction': 'Action',
    'audit.colDocument': 'Document',
    'audit.colActor': 'Actor',
    'audit.colDetail': 'Detail',
    'audit.system': 'system',
    'audit.changes': 'changes',
    'audit.before': 'before: {value}',
    'audit.after': 'after: {value}',

    // ---- data quality dashboard ----
    'dashboard.title': 'Data quality',
    'dashboard.dataHealthTitle': 'Registered data health',
    'dashboard.colDomain': 'Domain',
    'dashboard.colRecords': 'Records',
    'dashboard.colCompleteness': 'Completeness',
    'dashboard.colCompliance': 'Compliance',
    'dashboard.pipelineTitle': 'Pipeline health',
    'dashboard.extractionFailureRate': 'Extraction failure rate: {rate}%',
    'dashboard.openDuplicateCases': 'Open duplicate cases: {count}',
    'dashboard.noRecordsYet': 'No records yet',

    // ---- help page ----
    'help.title': 'How this works',
    'help.intro':
      'This is a reference for the whole document-to-record lifecycle — worth revisiting any time a rule (like who can approve what) needs a refresher, not just on your first visit.',
    'help.uploadTitle': '1. Upload a document',
    'help.uploadBody':
      'Anyone can submit a document (PDF only, for now) on the Intake page. One upload runs extraction for all three domains — Supplier, Client, and Product — at once, so you never need to re-upload the same file to check a different domain. Extraction runs locally against a local AI model; it can take a few minutes for all three domains to finish.',
    'help.reviewTitle': '2. Review the extracted candidate',
    'help.reviewBody':
      'Every extracted field shows a confidence score and where it came from (which page, which method). Low-confidence fields are flagged — check those against the source document before trusting them. A candidate always needs an explicit human decision before it becomes a real record; nothing is ever registered automatically, no matter how confident the extraction looks.',
    'help.decisionTitle': '3. Approve, reject, or request more info',
    'help.decisionBody':
      'Only approver accounts can make this decision, and approver accounts require two-factor authentication. Approving creates or updates the registered record. Rejecting discards the candidate. Requesting more info sends it back to the queue with your notes attached for whoever picks it up next.',
    'help.segregationTitle': 'Why you might not be able to approve your own upload',
    'help.segregationBody':
      'For Supplier candidates specifically, the person who submitted a document cannot also approve it — a different approver has to. This is a fraud-prevention control (segregation of duties), not a bug. Client and Product candidates don\'t require this because they carry less fraud risk.',
    'help.duplicatesTitle': '4. Duplicate matches',
    'help.duplicatesBody':
      'If a candidate\'s tax ID (CNPJ/CPF) or SKU exactly matches an existing record, it\'s automatically linked as a duplicate review case instead of going through the normal approve/reject flow. You\'ll see a side-by-side comparison and can accept all the new values, accept only specific fields that changed, or reject the update entirely. Matching is always exact — this system never guesses at a "probably the same" match.',
    'help.auditTitle': '5. The audit log',
    'help.auditBody':
      'Every submission, decision, and duplicate resolution is recorded permanently — who did it, when, and what changed. Admin accounts can review the full history at any time from the Audit log link.',
    'help.languageTitle': 'Switching language',
    'help.languageBody':
      'Use the EN/PT toggle (in the sidebar, or on the sign-in screen before you\'ve logged in) to switch the interface language at any time — your choice is remembered on this device.',

    // ---- domains ----
    'domain.supplier': 'Supplier',
    'domain.client': 'Client',
    'domain.product': 'Product',

    // ---- account roles ----
    'role.submitter': 'Submitter',
    'role.approver': 'Approver',
    'role.admin': 'Admin',

    // ---- job / case statuses ----
    'status.queued': 'Queued',
    'status.pending_review': 'Pending review',
    'status.needs_info': 'Needs info',
    'status.approved': 'Approved',
    'status.rejected': 'Rejected',
    'status.extraction_failed': 'Extraction failed',
    'status.unsupported_format': 'Unsupported format',
    'status.pending': 'Pending',
    'status.accepted': 'Accepted',
    'status.partially_accepted': 'Partially accepted',

    // ---- reliability ----
    'reliability.Excellent': 'Excellent',
    'reliability.Good': 'Good',
    'reliability.Low': 'Low',

    // ---- master/evidence field labels ----
    'field.cnpj': 'CNPJ',
    'field.tax_id': 'Tax ID',
    'field.legal_name': 'Legal name',
    'field.name': 'Name',
    'field.email': 'Email',
    'field.telephone': 'Telephone',
    'field.address': 'Address',
    'field.sku': 'SKU',
    'field.ncm': 'NCM',
    'field.description': 'Description',
    'field.price': 'Price',
    'field.quantity': 'Quantity',
    'field.discount': 'Discount',

    // ---- field display (confidence/provenance chrome) ----
    'fieldDisplay.notExtracted': 'Not extracted',
    'fieldDisplay.confidence': '{percent}% confidence',
    'fieldDisplay.page': 'Page {page}',
    'fieldDisplay.sourceWithPage': 'source: {source}, p.{page}',
    'fieldDisplay.source': 'source: {source}',
    'fieldDisplay.source.regex': 'pattern match',
    'fieldDisplay.source.llm': 'AI extraction',
    'fieldDisplay.source.pdf_layout': 'document layout',

    // ---- extracted party roles ----
    'partyRole.supplier': 'Supplier',
    'partyRole.client': 'Client',
    'partyRole.transporter': 'Transporter',
    'partyRole.intermediary': 'Intermediary',
    'partyRole.branch': 'Branch',
    'partyRole.unknown': 'Unknown',

    // ---- audit log actions ----
    'auditAction.submitted': 'Submitted',
    'auditAction.restored': 'Restored',
    'auditAction.approved': 'Approved',
    'auditAction.rejected': 'Rejected',
    'auditAction.needs_info': 'Needs info',
    'auditAction.link-duplicate': 'Linked duplicate',
    'auditAction.purged': 'Purged',
    'auditAction.edited': 'Edited',

    // ---- backend-generated (documents.py sets this directly on the job,
    // not via an HTTPException, so mdm.i18n doesn't cover it) ----
    'backend.extractionFailed': 'Extraction failed; see server logs for details',
  },
  pt: {
    // ---- common ----
    'common.loading': 'Carregando…',
    'common.none': '—',
    'common.yes': 'Sim',
    'common.job': 'Registro',
    'common.case': 'Caso',
    'common.editRequest': 'Solicitação de edição',
    'common.statusUpdateMessage': '{subject} agora está {status}.',

    // ---- layout / nav ----
    'layout.brandCaption': 'Registro de Dados Mestres',
    'layout.pageTitle': 'MDM — Registro de Dados Mestres',
    'layout.navIntake': 'Entrada',
    'layout.navDashboard': 'Painel',
    'layout.navQueuesSection': 'Filas',
    'layout.navMasterDataSection': 'Dados Mestres',
    'layout.navRecordsSection': 'Registros',
    'layout.navAuditLog': 'Log de auditoria',
    'layout.navHelp': 'Ajuda',
    'layout.logout': 'Sair',
    'layout.languageToggleLabel': 'Idioma',

    // ---- login page ----
    'login.title': 'Entrar',
    'login.username': 'Usuário',
    'login.password': 'Senha',
    'login.authenticatorCode': 'Código do autenticador',
    'login.authenticatorHint': ' (somente contas de aprovador, após o cadastro)',
    'login.submitting': 'Entrando…',
    'login.submit': 'Entrar',

    // ---- MFA enrollment page ----
    'mfaEnroll.doneTitle': 'Autenticação de dois fatores ativada',
    'mfaEnroll.doneBody': 'Entre novamente com seu usuário, senha e um código atual do autenticador.',
    'mfaEnroll.goToSignIn': 'Ir para o login',
    'mfaEnroll.title': 'Configurar autenticação de dois fatores',
    'mfaEnroll.introPrefix': 'A conta de aprovador ',
    'mfaEnroll.introSuffix': ' requer um aplicativo autenticador antes de poder ser usada.',
    'mfaEnroll.manualCodePrefix': 'Ou digite este código manualmente: ',
    'mfaEnroll.codeLabel': 'Digite o código de 6 dígitos do seu aplicativo autenticador',
    'mfaEnroll.verifying': 'Verificando…',
    'mfaEnroll.confirm': 'Confirmar',

    // ---- home page ----
    'home.welcome': 'Bem-vindo',
    'home.intro': 'Registro de dados mestres — envie um documento e depois revise os candidatos nas filas abaixo.',
    'home.uploadLink': 'Enviar um documento',
    'home.queueLink': 'Fila de revisão de {domain}',
    'home.helpLink': 'Como funciona',

    // ---- upload page ----
    'upload.title': 'Enviar um documento',
    'upload.intro': 'Candidatos de Fornecedor, Cliente e Produto são todos extraídos de um único envio.',
    'upload.file': 'Arquivo',
    'upload.submitting': 'Enviando e extraindo…',
    'upload.submit': 'Enviar',
    'upload.progressLabel': 'Extraindo o documento — isso pode levar alguns minutos…',
    'upload.resultsTitle': 'Resultados da extração',
    'upload.colDomain': 'Domínio',
    'upload.colStatus': 'Status',
    'upload.colDuplicate': 'Duplicidade?',
    'upload.viewJob': 'Ver registro',
    'upload.another': 'Enviar outro',

    // ---- queue page ----
    'queue.title': 'Fila de revisão de {domain}',
    'queue.filterNeedsReview': 'Precisa de revisão',
    'queue.filterNeedsInfo': 'Precisa de informações',
    'queue.filterApproved': 'Aprovado',
    'queue.filterRejected': 'Rejeitado',
    'queue.filterAll': 'Todos',
    'queue.truncatedNotice':
      'Mostrando os 200 registros correspondentes mais recentes — os mais antigos não são exibidos. Restrinja o filtro de status acima para ver mais.',
    'queue.empty': 'Nenhum registro corresponde a este filtro.',
    'queue.colStatus': 'Status',
    'queue.colCreated': 'Criado em',
    'queue.colSubmittedBy': 'Enviado por',
    'queue.colDuplicate': 'Duplicidade?',
    'queue.review': 'Revisar',

    // ---- master data (consult/search + detail) ----
    'masterData.title': 'Dados mestres de {domain}',
    'masterData.searchPlaceholder': 'Buscar por qualquer valor de campo…',
    'masterData.empty': 'Nenhum registro corresponde a este filtro.',
    'masterData.colKey': 'Chave',
    'masterData.colPreview': 'Prévia',
    'masterData.colVersion': 'Versão',
    'masterData.view': 'Ver',
    'masterData.loadMore': 'Carregar mais',
    'masterData.detailTitle': 'Registro de {domain}',
    'masterData.key': 'Chave: {key}',
    'masterData.version': 'Versão {version}',
    'masterData.firstRegistered': 'Cadastrado em: {date}',
    'masterData.lastUpdated': 'Atualizado em: {date}',
    'masterData.fieldsTitle': 'Campos',
    'masterData.edit': 'Editar',
    'masterData.save': 'Salvar',
    'masterData.cancel': 'Cancelar',
    'masterData.editSuccess': 'Registro atualizado.',
    'masterData.keyFieldReadOnlyHint': 'O campo-chave não pode ser editado aqui.',
    'masterData.proposeEdit': 'Propor edição',
    'masterData.proposeEditSubmit': 'Enviar proposta',
    'masterData.pendingEditBanner': 'Há uma solicitação de edição pendente para este registro.',
    'masterData.reviewEditRequest': 'Revisar solicitação de edição',
    'masterData.editRequestSubmitted': 'Solicitação de edição enviada — outro aprovador deve revisá-la.',

    // ---- edit request review page ----
    'editRequest.title': 'Revisão de solicitação de edição',
    'editRequest.segregationBanner': 'Você enviou esta solicitação de edição — outro aprovador deve revisá-la.',
    'editRequest.segregationTitle': 'Você não pode aprovar sua própria solicitação de edição',
    'editRequest.approverOnlyHint': 'Somente contas de aprovador podem revisar uma solicitação de edição.',

    // ---- review detail page ----
    'review.candidateTitle': 'Candidato de {domain}',
    'review.duplicateFoundBanner': 'Um registro correspondente foi encontrado para este candidato.',
    'review.resolveDuplicate': 'Resolver duplicidade',
    'review.scoringTitle': 'Pontuação',
    'review.scoringSummary':
      'Confiabilidade: {reliability} · Completude: {completeness}% · Conformidade: {compliance}%',
    'review.missingRequired': 'Obrigatório(s) ausente(s): {fields}',
    'review.lowConfidence': 'Baixa confiança: {fields}',
    'review.fieldsTitle': 'Campos extraídos',
    'review.copyRawJson': 'Copiar JSON bruto',
    'review.evidenceTitle': 'Evidência transacional (não faz parte do registro cadastrado)',
    'review.partiesTitle': 'Partes identificadas neste documento',
    'review.inferredRole': ' (inferido pela posição, não é uma etiqueta correspondida — verifique)',
    'review.inferredRoleTitle': 'Deduzido pela posição no documento — nenhuma etiqueta foi encontrada; verifique este item',
    'review.matchedRole': ' (correspondeu a "{label}")',
    'review.decisionTitle': 'Decisão',
    'review.notes': 'Observações',
    'review.overridesHint': 'Atribua um valor para qualquer campo ausente no candidato antes de aprovar como novo:',
    'review.segregationApproveBanner':
      'Você enviou este candidato de {domain} — a segregação de funções significa que você não pode aprovar sua própria submissão. Rejeite ou solicite mais informações, ou peça que outro aprovador revise.',
    'review.segregationApproveTitle': 'Você não pode aprovar sua própria submissão para este domínio',
    'review.approve': 'Aprovar',
    'review.reject': 'Rejeitar',
    'review.requestInfo': 'Solicitar informações',
    'review.notesRequired': 'Observações são obrigatórias ao solicitar mais informações.',
    'review.searchSummary': 'Buscar um {domain} existente para vincular este candidato',
    'review.searchPlaceholder': 'Buscar por qualquer valor de campo extraído…',
    'review.search': 'Buscar',
    'review.noMatches': 'Nenhum resultado.',
    'review.link': 'Vincular',
    'review.approverOnlyHint': 'Somente contas de aprovador podem aprovar, rejeitar ou solicitar mais informações.',

    // ---- duplicate resolve page ----
    'duplicate.title': 'Revisão de duplicidade',
    'duplicate.matchedOnManual': 'vinculado manualmente por um revisor',
    'duplicate.matchedOn': 'Correspondido por: {key}',
    'duplicate.colField': 'Campo',
    'duplicate.colExisting': 'Valor existente',
    'duplicate.colNew': 'Novo valor',
    'duplicate.colAccept': 'Aceitar este campo?',
    'duplicate.notes': 'Observações',
    'duplicate.segregationBanner':
      'Você enviou este candidato de {domain} — a segregação de funções significa que você não pode aceitar uma atualização da sua própria submissão. Você ainda pode rejeitá-la, ou pedir que outro aprovador resolva.',
    'duplicate.segregationTitle': 'Você não pode resolver uma duplicidade da sua própria submissão',
    'duplicate.selectFieldTitle': 'Selecione ao menos um campo divergente acima',
    'duplicate.acceptAll': 'Aceitar tudo',
    'duplicate.acceptSelected': 'Aceitar campos selecionados',
    'duplicate.acceptSelectedCount': 'Aceitar campos selecionados ({count} selecionado(s))',
    'duplicate.reject': 'Rejeitar',
    'duplicate.approverOnlyHint': 'Somente contas de aprovador podem resolver um caso de revisão de duplicidade.',

    // ---- audit page ----
    'audit.title': 'Log de auditoria',
    'audit.filterPlaceholder': 'Filtrar por id do documento…',
    'audit.filter': 'Filtrar',
    'audit.colWhen': 'Quando',
    'audit.colAction': 'Ação',
    'audit.colDocument': 'Documento',
    'audit.colActor': 'Autor',
    'audit.colDetail': 'Detalhe',
    'audit.system': 'sistema',
    'audit.changes': 'alterações',
    'audit.before': 'antes: {value}',
    'audit.after': 'depois: {value}',

    // ---- data quality dashboard ----
    'dashboard.title': 'Qualidade dos dados',
    'dashboard.dataHealthTitle': 'Saúde dos dados cadastrados',
    'dashboard.colDomain': 'Domínio',
    'dashboard.colRecords': 'Registros',
    'dashboard.colCompleteness': 'Completude',
    'dashboard.colCompliance': 'Conformidade',
    'dashboard.pipelineTitle': 'Saúde do fluxo',
    'dashboard.extractionFailureRate': 'Taxa de falha na extração: {rate}%',
    'dashboard.openDuplicateCases': 'Casos de duplicidade em aberto: {count}',
    'dashboard.noRecordsYet': 'Nenhum registro ainda',

    // ---- help page ----
    'help.title': 'Como funciona',
    'help.intro':
      'Esta é uma referência para todo o ciclo de vida do documento até o registro — vale revisitar sempre que uma regra (como quem pode aprovar o quê) precisar ser relembrada, não só na sua primeira visita.',
    'help.uploadTitle': '1. Envie um documento',
    'help.uploadBody':
      'Qualquer pessoa pode enviar um documento (somente PDF, por enquanto) na página Entrada. Um único envio executa a extração para os três domínios — Fornecedor, Cliente e Produto — de uma só vez, então você nunca precisa reenviar o mesmo arquivo para verificar um domínio diferente. A extração roda localmente com um modelo de IA local; pode levar alguns minutos até que os três domínios terminem.',
    'help.reviewTitle': '2. Revise o candidato extraído',
    'help.reviewBody':
      'Todo campo extraído mostra uma pontuação de confiança e de onde veio (qual página, qual método). Campos de baixa confiança são sinalizados — confira-os no documento original antes de confiar neles. Um candidato sempre precisa de uma decisão humana explícita antes de se tornar um registro real; nada é cadastrado automaticamente, não importa quão confiante pareça a extração.',
    'help.decisionTitle': '3. Aprove, rejeite ou solicite mais informações',
    'help.decisionBody':
      'Somente contas de aprovador podem tomar essa decisão, e contas de aprovador exigem autenticação de dois fatores. Aprovar cria ou atualiza o registro cadastrado. Rejeitar descarta o candidato. Solicitar mais informações devolve o candidato à fila com suas observações anexadas para quem for atendê-lo em seguida.',
    'help.segregationTitle': 'Por que você pode não conseguir aprovar seu próprio envio',
    'help.segregationBody':
      'Especificamente para candidatos de Fornecedor, quem enviou um documento não pode também aprová-lo — outro aprovador precisa fazê-lo. Este é um controle de prevenção a fraude (segregação de funções), não um erro. Candidatos de Cliente e Produto não exigem isso porque carregam menos risco de fraude.',
    'help.duplicatesTitle': '4. Correspondências de duplicidade',
    'help.duplicatesBody':
      'Se o CNPJ/CPF ou SKU de um candidato corresponder exatamente a um registro existente, ele é automaticamente vinculado como um caso de revisão de duplicidade em vez de seguir o fluxo normal de aprovação/rejeição. Você verá uma comparação lado a lado e poderá aceitar todos os novos valores, aceitar apenas campos específicos que mudaram, ou rejeitar a atualização por completo. A correspondência é sempre exata — este sistema nunca supõe uma correspondência "provável".',
    'help.auditTitle': '5. O log de auditoria',
    'help.auditBody':
      'Cada envio, decisão e resolução de duplicidade é registrado permanentemente — quem fez, quando e o que mudou. Contas de administrador podem revisar o histórico completo a qualquer momento pelo link Log de auditoria.',
    'help.languageTitle': 'Trocando o idioma',
    'help.languageBody':
      'Use o alternador EN/PT (na barra lateral, ou na tela de login antes de entrar) para trocar o idioma da interface a qualquer momento — sua escolha é lembrada neste dispositivo.',

    // ---- domains ----
    'domain.supplier': 'Fornecedor',
    'domain.client': 'Cliente',
    'domain.product': 'Produto',

    // ---- account roles ----
    'role.submitter': 'Solicitante',
    'role.approver': 'Aprovador',
    'role.admin': 'Administrador',

    // ---- job / case statuses ----
    'status.queued': 'Na fila',
    'status.pending_review': 'Aguardando revisão',
    'status.needs_info': 'Precisa de informações',
    'status.approved': 'Aprovado',
    'status.rejected': 'Rejeitado',
    'status.extraction_failed': 'Falha na extração',
    'status.unsupported_format': 'Formato não suportado',
    'status.pending': 'Pendente',
    'status.accepted': 'Aceito',
    'status.partially_accepted': 'Parcialmente aceito',

    // ---- reliability ----
    'reliability.Excellent': 'Excelente',
    'reliability.Good': 'Boa',
    'reliability.Low': 'Baixa',

    // ---- master/evidence field labels ----
    'field.cnpj': 'CNPJ',
    'field.tax_id': 'CPF/CNPJ',
    'field.legal_name': 'Razão social',
    'field.name': 'Nome',
    'field.email': 'E-mail',
    'field.telephone': 'Telefone',
    'field.address': 'Endereço',
    'field.sku': 'SKU',
    'field.ncm': 'NCM',
    'field.description': 'Descrição',
    'field.price': 'Preço',
    'field.quantity': 'Quantidade',
    'field.discount': 'Desconto',

    // ---- field display (confidence/provenance chrome) ----
    'fieldDisplay.notExtracted': 'Não extraído',
    'fieldDisplay.confidence': '{percent}% de confiança',
    'fieldDisplay.page': 'Página {page}',
    'fieldDisplay.sourceWithPage': 'origem: {source}, p.{page}',
    'fieldDisplay.source': 'origem: {source}',
    'fieldDisplay.source.regex': 'correspondência de padrão',
    'fieldDisplay.source.llm': 'extração por IA',
    'fieldDisplay.source.pdf_layout': 'layout do documento',

    // ---- extracted party roles ----
    'partyRole.supplier': 'Fornecedor',
    'partyRole.client': 'Cliente',
    'partyRole.transporter': 'Transportadora',
    'partyRole.intermediary': 'Intermediário',
    'partyRole.branch': 'Filial',
    'partyRole.unknown': 'Desconhecido',

    // ---- audit log actions ----
    'auditAction.submitted': 'Enviado',
    'auditAction.restored': 'Restaurado',
    'auditAction.approved': 'Aprovado',
    'auditAction.rejected': 'Rejeitado',
    'auditAction.needs_info': 'Precisa de informações',
    'auditAction.link-duplicate': 'Duplicidade vinculada',
    'auditAction.purged': 'Expurgado',
    'auditAction.edited': 'Editado',

    // ---- backend-generated (documents.py sets this directly on the job,
    // not via an HTTPException, so mdm.i18n doesn't cover it) ----
    'backend.extractionFailed': 'Falha na extração; consulte os logs do servidor para mais detalhes',
  },
}
