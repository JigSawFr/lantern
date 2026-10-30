"""The reference server's own texts for people (SPEC.md § 2.2): each error
code's title, and a detail that stands for the English one's specifics, in
the fifteen languages of Boréale's sites (site/i18n/). English is the
server's own words, given where the error is raised; the others are here.

best() picks, for an Accept-Language, the language of these texts: an exact
tag, a region's variant (fr-CA, es-419 and the Spanish of the Americas,
pt-BR, zh-Hans and zh-Hant by script or region), else the language alone,
else English.
"""

LANGUAGES = ("en", "fr", "fr-CA", "de", "es", "es-419", "it", "nl", "pt", "pt-BR", "ru", "ja", "ko", "zh-Hans",
             "zh-Hant")
AMERICAS = {"419", "ar", "bo", "cl", "co", "cr", "cu", "do", "ec", "gt", "hn", "mx", "ni", "pa", "pe", "pr", "py",
            "sv", "us", "uy", "ve"}
HANT = {"hant", "tw", "hk", "mo"}

FR = {
    "bad_request": ("Requête incorrecte", "La requête est mal formée ; sa documentation dit la forme attendue."),
    "key_required": ("Clé de l’appareil requise",
                     "Ce serveur n’associe un jeton qu’à une clé de l’appareil : envoyez-en une à l’appairage."),
    "unauthorized": ("Non autorisé", "Jeton absent, inconnu, révoqué ou expiré : appairez cet appareil."),
    "signature_required": ("Signature requise", "Ce jeton est lié à la clé de l’appareil : signez la requête."),
    "signature_invalid": ("Signature invalide", "La signature ne se vérifie pas, ou n’a pas la forme attendue."),
    "signature_expired": ("Signature périmée",
                          "L’heure de la signature est trop loin de celle du serveur : réglez-la sur son en-tête Date."),
    "signature_replayed": ("Signature rejouée", "Ce nonce a déjà servi : un nouveau pour chaque requête."),
    "forbidden": ("Interdit", "Ce compte n’a pas le droit de faire cela."),
    "account_frozen": ("Compte gelé", "Ce compte ne peut rien faire pour l’instant."),
    "not_found": ("Introuvable", "Rien de tel sur ce serveur."),
    "conflict": ("Conflit", "Cela existe déjà, a changé entre-temps, ou l’envoi n’en est pas là."),
    "gone": ("Disparu", "Expiré, révoqué, épuisé ou inconnu."),
    "precondition_failed": ("Condition non remplie", "Les données ont changé depuis votre lecture : relisez-les."),
    "too_large": ("Trop grand", "Au-delà des limites de ce serveur."),
    "unsupported_schema": ("Schéma non pris en charge", "Ce serveur ne lit pas ce schéma de document."),
    "digest_mismatch": ("Empreinte différente", "Le SHA-256 du corps n’est pas celui annoncé."),
    "slow_down": ("Ralentissez", "Trop de requêtes : réessayez après le délai indiqué."),
    "internal": ("Erreur interne", "Le serveur a échoué ; réessayez plus tard."),
    "unavailable": ("Indisponible", "Le serveur est occupé ou en maintenance ; réessayez plus tard."),
}

DE = {
    "bad_request": ("Ungültige Anfrage", "Die Anfrage ist fehlerhaft; ihre Dokumentation nennt die erwartete Form."),
    "key_required": ("Geräteschlüssel erforderlich",
                     "Dieser Server bindet jedes Token an einen Geräteschlüssel: Senden Sie einen beim Koppeln."),
    "unauthorized": ("Nicht autorisiert", "Token fehlt, ist unbekannt, widerrufen oder abgelaufen: Koppeln Sie dieses Gerät."),
    "signature_required": ("Signatur erforderlich", "Dieses Token ist an den Geräteschlüssel gebunden: Signieren Sie die Anfrage."),
    "signature_invalid": ("Ungültige Signatur", "Die Signatur lässt sich nicht prüfen oder hat nicht die erwartete Form."),
    "signature_expired": ("Signatur abgelaufen",
                          "Die Zeit der Signatur weicht zu sehr von der des Servers ab: Richten Sie sie nach seinem Date-Header."),
    "signature_replayed": ("Signatur wiederholt", "Diese Nonce wurde schon verwendet: eine neue für jede Anfrage."),
    "forbidden": ("Verboten", "Dieses Konto darf das nicht."),
    "account_frozen": ("Konto eingefroren", "Dieses Konto kann vorerst nichts tun."),
    "not_found": ("Nicht gefunden", "Nichts dergleichen auf diesem Server."),
    "conflict": ("Konflikt", "Das gibt es schon, es hat sich inzwischen geändert, oder der Upload steht woanders."),
    "gone": ("Nicht mehr verfügbar", "Abgelaufen, widerrufen, aufgebraucht oder unbekannt."),
    "precondition_failed": ("Vorbedingung nicht erfüllt", "Die Daten haben sich seit dem Lesen geändert: Lesen Sie sie neu."),
    "too_large": ("Zu groß", "Über den Grenzen dieses Servers."),
    "unsupported_schema": ("Schema nicht unterstützt", "Dieser Server liest dieses Dokumentschema nicht."),
    "digest_mismatch": ("Prüfsumme abweichend", "Der SHA-256 des Inhalts ist nicht der angekündigte."),
    "slow_down": ("Langsamer", "Zu viele Anfragen: Versuchen Sie es nach der genannten Wartezeit erneut."),
    "internal": ("Interner Fehler", "Der Server ist gescheitert; versuchen Sie es später erneut."),
    "unavailable": ("Nicht verfügbar", "Der Server ist beschäftigt oder in Wartung; versuchen Sie es später erneut."),
}

ES = {
    "bad_request": ("Solicitud incorrecta", "La solicitud está mal formada; su documentación indica la forma esperada."),
    "key_required": ("Se requiere la clave del dispositivo",
                     "Este servidor vincula cada token a una clave del dispositivo: envíe una al emparejar."),
    "unauthorized": ("No autorizado", "Token ausente, desconocido, revocado o caducado: empareje este dispositivo."),
    "signature_required": ("Se requiere firma", "Este token está vinculado a la clave del dispositivo: firme la solicitud."),
    "signature_invalid": ("Firma no válida", "La firma no se verifica o no tiene la forma esperada."),
    "signature_expired": ("Firma caducada",
                          "La hora de la firma está demasiado lejos de la del servidor: ajústela a su cabecera Date."),
    "signature_replayed": ("Firma repetida", "Este nonce ya se usó: uno nuevo para cada solicitud."),
    "forbidden": ("Prohibido", "Esta cuenta no puede hacer eso."),
    "account_frozen": ("Cuenta congelada", "Esta cuenta no puede hacer nada por ahora."),
    "not_found": ("No encontrado", "Nada parecido en este servidor."),
    "conflict": ("Conflicto", "Ya existe, cambió entretanto, o el envío no va por ahí."),
    "gone": ("Ya no existe", "Caducado, revocado, agotado o desconocido."),
    "precondition_failed": ("Condición no cumplida", "Los datos cambiaron desde que los leyó: vuelva a leerlos."),
    "too_large": ("Demasiado grande", "Por encima de los límites de este servidor."),
    "unsupported_schema": ("Esquema no admitido", "Este servidor no lee este esquema de documento."),
    "digest_mismatch": ("Huella distinta", "El SHA-256 del cuerpo no es el anunciado."),
    "slow_down": ("Más despacio", "Demasiadas solicitudes: vuelva a intentarlo tras el plazo indicado."),
    "internal": ("Error interno", "El servidor ha fallado; vuelva a intentarlo más tarde."),
    "unavailable": ("No disponible", "El servidor está ocupado o en mantenimiento; vuelva a intentarlo más tarde."),
}

ES_419 = {**ES,
          "key_required": ("Se requiere la clave del dispositivo",
                           "Este servidor vincula cada token a una clave del dispositivo: envía una al emparejar."),
          "unauthorized": ("No autorizado", "Token ausente, desconocido, revocado o vencido: empareja este dispositivo."),
          "signature_required": ("Se requiere firma", "Este token está vinculado a la clave del dispositivo: firma la solicitud."),
          "signature_expired": ("Firma vencida",
                                "La hora de la firma está demasiado lejos de la del servidor: ajústala a su encabezado Date."),
          "gone": ("Ya no existe", "Vencido, revocado, agotado o desconocido."),
          "precondition_failed": ("Condición no cumplida", "Los datos cambiaron desde que los leíste: vuelve a leerlos."),
          "slow_down": ("Más despacio", "Demasiadas solicitudes: vuelve a intentarlo después del plazo indicado."),
          "internal": ("Error interno", "El servidor falló; vuelve a intentarlo más tarde."),
          "unavailable": ("No disponible", "El servidor está ocupado o en mantenimiento; vuelve a intentarlo más tarde."),
          "bad_request": ("Solicitud incorrecta", "La solicitud está mal formada; su documentación indica la forma esperada."),
          }

IT = {
    "bad_request": ("Richiesta non valida", "La richiesta è malformata; la sua documentazione indica la forma attesa."),
    "key_required": ("Chiave del dispositivo richiesta",
                     "Questo server lega ogni token a una chiave del dispositivo: inviane una all’abbinamento."),
    "unauthorized": ("Non autorizzato", "Token assente, sconosciuto, revocato o scaduto: abbina questo dispositivo."),
    "signature_required": ("Firma richiesta", "Questo token è legato alla chiave del dispositivo: firma la richiesta."),
    "signature_invalid": ("Firma non valida", "La firma non si verifica o non ha la forma attesa."),
    "signature_expired": ("Firma scaduta",
                          "L’ora della firma è troppo lontana da quella del server: regolala sulla sua intestazione Date."),
    "signature_replayed": ("Firma ripetuta", "Questo nonce è già stato usato: uno nuovo per ogni richiesta."),
    "forbidden": ("Vietato", "Questo account non può farlo."),
    "account_frozen": ("Account congelato", "Questo account per ora non può fare nulla."),
    "not_found": ("Non trovato", "Niente del genere su questo server."),
    "conflict": ("Conflitto", "Esiste già, è cambiato nel frattempo, oppure l’invio non è a quel punto."),
    "gone": ("Non più disponibile", "Scaduto, revocato, esaurito o sconosciuto."),
    "precondition_failed": ("Condizione non soddisfatta", "I dati sono cambiati dalla tua lettura: rileggili."),
    "too_large": ("Troppo grande", "Oltre i limiti di questo server."),
    "unsupported_schema": ("Schema non supportato", "Questo server non legge questo schema di documento."),
    "digest_mismatch": ("Impronta diversa", "Lo SHA-256 del corpo non è quello annunciato."),
    "slow_down": ("Rallenta", "Troppe richieste: riprova dopo l’attesa indicata."),
    "internal": ("Errore interno", "Il server ha avuto un errore; riprova più tardi."),
    "unavailable": ("Non disponibile", "Il server è occupato o in manutenzione; riprova più tardi."),
}

NL = {
    "bad_request": ("Ongeldig verzoek", "Het verzoek is onjuist opgebouwd; de documentatie geeft de verwachte vorm."),
    "key_required": ("Apparaatsleutel vereist",
                     "Deze server koppelt elk token aan een apparaatsleutel: stuur er een mee bij het koppelen."),
    "unauthorized": ("Niet geautoriseerd", "Token ontbreekt, is onbekend, ingetrokken of verlopen: koppel dit apparaat."),
    "signature_required": ("Handtekening vereist", "Dit token hoort bij de apparaatsleutel: onderteken het verzoek."),
    "signature_invalid": ("Ongeldige handtekening", "De handtekening klopt niet of heeft niet de verwachte vorm."),
    "signature_expired": ("Handtekening verlopen",
                          "De tijd van de handtekening wijkt te ver af van die van de server: stel hem af op zijn Date-header."),
    "signature_replayed": ("Handtekening herhaald", "Deze nonce is al gebruikt: een nieuwe voor elk verzoek."),
    "forbidden": ("Verboden", "Dit account mag dat niet."),
    "account_frozen": ("Account bevroren", "Dit account kan voorlopig niets doen."),
    "not_found": ("Niet gevonden", "Niets van dien aard op deze server."),
    "conflict": ("Conflict", "Dat bestaat al, is intussen gewijzigd, of de upload staat elders."),
    "gone": ("Verdwenen", "Verlopen, ingetrokken, opgebruikt of onbekend."),
    "precondition_failed": ("Voorwaarde niet vervuld", "De gegevens zijn gewijzigd sinds u ze las: lees ze opnieuw."),
    "too_large": ("Te groot", "Boven de grenzen van deze server."),
    "unsupported_schema": ("Schema niet ondersteund", "Deze server leest dit documentschema niet."),
    "digest_mismatch": ("Afwijkende hash", "De SHA-256 van de inhoud is niet de aangekondigde."),
    "slow_down": ("Rustig aan", "Te veel verzoeken: probeer het opnieuw na de aangegeven wachttijd."),
    "internal": ("Interne fout", "De server faalde; probeer het later opnieuw."),
    "unavailable": ("Niet beschikbaar", "De server is bezet of in onderhoud; probeer het later opnieuw."),
}

PT = {
    "bad_request": ("Pedido inválido", "O pedido está mal formado; a sua documentação indica a forma esperada."),
    "key_required": ("Chave do dispositivo necessária",
                     "Este servidor associa cada token a uma chave do dispositivo: envie uma ao emparelhar."),
    "unauthorized": ("Não autorizado", "Token ausente, desconhecido, revogado ou expirado: emparelhe este dispositivo."),
    "signature_required": ("Assinatura necessária", "Este token está associado à chave do dispositivo: assine o pedido."),
    "signature_invalid": ("Assinatura inválida", "A assinatura não se verifica ou não tem a forma esperada."),
    "signature_expired": ("Assinatura expirada",
                          "A hora da assinatura está demasiado longe da do servidor: acerte-a pelo cabeçalho Date."),
    "signature_replayed": ("Assinatura repetida", "Este nonce já foi usado: um novo para cada pedido."),
    "forbidden": ("Proibido", "Esta conta não pode fazer isso."),
    "account_frozen": ("Conta congelada", "Esta conta não pode fazer nada por agora."),
    "not_found": ("Não encontrado", "Nada disso neste servidor."),
    "conflict": ("Conflito", "Já existe, mudou entretanto, ou o envio não está nesse ponto."),
    "gone": ("Já não existe", "Expirado, revogado, esgotado ou desconhecido."),
    "precondition_failed": ("Condição não cumprida", "Os dados mudaram desde a sua leitura: leia-os de novo."),
    "too_large": ("Demasiado grande", "Acima dos limites deste servidor."),
    "unsupported_schema": ("Esquema não suportado", "Este servidor não lê este esquema de documento."),
    "digest_mismatch": ("Impressão diferente", "O SHA-256 do corpo não é o anunciado."),
    "slow_down": ("Mais devagar", "Demasiados pedidos: tente de novo após o tempo indicado."),
    "internal": ("Erro interno", "O servidor falhou; tente de novo mais tarde."),
    "unavailable": ("Indisponível", "O servidor está ocupado ou em manutenção; tente de novo mais tarde."),
}

PT_BR = {
    "bad_request": ("Solicitação inválida", "A solicitação está malformada; a documentação indica o formato esperado."),
    "key_required": ("Chave do dispositivo obrigatória",
                     "Este servidor vincula cada token a uma chave do dispositivo: envie uma ao parear."),
    "unauthorized": ("Não autorizado", "Token ausente, desconhecido, revogado ou expirado: pareie este dispositivo."),
    "signature_required": ("Assinatura obrigatória", "Este token está vinculado à chave do dispositivo: assine a solicitação."),
    "signature_invalid": ("Assinatura inválida", "A assinatura não confere ou não tem o formato esperado."),
    "signature_expired": ("Assinatura expirada",
                          "O horário da assinatura está longe demais do servidor: ajuste-o pelo cabeçalho Date."),
    "signature_replayed": ("Assinatura repetida", "Este nonce já foi usado: um novo para cada solicitação."),
    "forbidden": ("Proibido", "Esta conta não pode fazer isso."),
    "account_frozen": ("Conta congelada", "Esta conta não pode fazer nada por enquanto."),
    "not_found": ("Não encontrado", "Nada disso neste servidor."),
    "conflict": ("Conflito", "Já existe, mudou nesse meio-tempo, ou o envio não está nesse ponto."),
    "gone": ("Não existe mais", "Expirado, revogado, esgotado ou desconhecido."),
    "precondition_failed": ("Condição não atendida", "Os dados mudaram desde a sua leitura: leia de novo."),
    "too_large": ("Grande demais", "Acima dos limites deste servidor."),
    "unsupported_schema": ("Esquema não suportado", "Este servidor não lê este esquema de documento."),
    "digest_mismatch": ("Hash diferente", "O SHA-256 do corpo não é o informado."),
    "slow_down": ("Mais devagar", "Solicitações demais: tente de novo depois do tempo indicado."),
    "internal": ("Erro interno", "O servidor falhou; tente de novo mais tarde."),
    "unavailable": ("Indisponível", "O servidor está ocupado ou em manutenção; tente de novo mais tarde."),
}

RU = {
    "bad_request": ("Неверный запрос", "Запрос составлен неверно; ожидаемая форма описана в документации."),
    "key_required": ("Нужен ключ устройства",
                     "Этот сервер привязывает каждый токен к ключу устройства: отправьте его при сопряжении."),
    "unauthorized": ("Нет доступа", "Токена нет, он неизвестен, отозван или истёк: выполните сопряжение устройства."),
    "signature_required": ("Нужна подпись", "Этот токен привязан к ключу устройства: подпишите запрос."),
    "signature_invalid": ("Неверная подпись", "Подпись не проходит проверку или имеет не ту форму."),
    "signature_expired": ("Подпись устарела",
                          "Время подписи слишком далеко от времени сервера: сверьте его по заголовку Date."),
    "signature_replayed": ("Повтор подписи", "Этот nonce уже использован: для каждого запроса нужен новый."),
    "forbidden": ("Запрещено", "Этой учётной записи это не разрешено."),
    "account_frozen": ("Учётная запись заморожена", "Пока эта учётная запись ничего не может делать."),
    "not_found": ("Не найдено", "На этом сервере такого нет."),
    "conflict": ("Конфликт", "Это уже есть, изменилось за это время, или загрузка находится в другом месте."),
    "gone": ("Больше нет", "Истекло, отозвано, исчерпано или неизвестно."),
    "precondition_failed": ("Условие не выполнено", "Данные изменились после чтения: прочитайте их снова."),
    "too_large": ("Слишком большой", "Превышены пределы этого сервера."),
    "unsupported_schema": ("Схема не поддерживается", "Этот сервер не читает эту схему документа."),
    "digest_mismatch": ("Хэш не совпадает", "SHA-256 тела не тот, что был объявлен."),
    "slow_down": ("Помедленнее", "Слишком много запросов: повторите после указанной паузы."),
    "internal": ("Внутренняя ошибка", "Сбой сервера; повторите позже."),
    "unavailable": ("Недоступно", "Сервер занят или на обслуживании; повторите позже."),
}

JA = {
    "bad_request": ("不正なリクエスト", "リクエストの形式が正しくありません。期待される形式はドキュメントを参照してください。"),
    "key_required": ("デバイスキーが必要です", "このサーバーはトークンをデバイスキーに結び付けます。ペアリング時にキーを送ってください。"),
    "unauthorized": ("認証されていません", "トークンがない、不明、失効、または期限切れです。このデバイスをペアリングしてください。"),
    "signature_required": ("署名が必要です", "このトークンはデバイスキーに結び付いています。リクエストに署名してください。"),
    "signature_invalid": ("署名が無効です", "署名を検証できないか、期待される形式ではありません。"),
    "signature_expired": ("署名の期限切れ", "署名の時刻がサーバーの時刻と離れすぎています。Date ヘッダーに合わせてください。"),
    "signature_replayed": ("署名の再送", "この nonce は使用済みです。リクエストごとに新しいものを使ってください。"),
    "forbidden": ("禁止されています", "このアカウントにはその操作が許可されていません。"),
    "account_frozen": ("アカウント凍結中", "このアカウントは現在何もできません。"),
    "not_found": ("見つかりません", "このサーバーにはありません。"),
    "conflict": ("競合", "すでに存在するか、途中で変更されたか、アップロードの位置が違います。"),
    "gone": ("存在しません", "期限切れ、失効、使い切り、または不明です。"),
    "precondition_failed": ("前提条件を満たしていません", "読み込み後にデータが変わりました。もう一度読み込んでください。"),
    "too_large": ("大きすぎます", "このサーバーの上限を超えています。"),
    "unsupported_schema": ("対応していないスキーマ", "このサーバーはこのドキュメントのスキーマを読めません。"),
    "digest_mismatch": ("ハッシュが一致しません", "本文の SHA-256 が通知されたものと異なります。"),
    "slow_down": ("間隔をあけてください", "リクエストが多すぎます。指定された時間の後に再試行してください。"),
    "internal": ("内部エラー", "サーバーでエラーが発生しました。後でもう一度お試しください。"),
    "unavailable": ("利用できません", "サーバーが混雑中またはメンテナンス中です。後でもう一度お試しください。"),
}

KO = {
    "bad_request": ("잘못된 요청", "요청 형식이 올바르지 않습니다. 기대하는 형식은 문서를 참고하세요."),
    "key_required": ("기기 키 필요", "이 서버는 모든 토큰을 기기 키에 연결합니다. 페어링할 때 키를 보내세요."),
    "unauthorized": ("인증되지 않음", "토큰이 없거나 알 수 없거나 취소되었거나 만료되었습니다. 이 기기를 페어링하세요."),
    "signature_required": ("서명 필요", "이 토큰은 기기 키에 연결되어 있습니다. 요청에 서명하세요."),
    "signature_invalid": ("잘못된 서명", "서명이 검증되지 않거나 기대하는 형식이 아닙니다."),
    "signature_expired": ("서명 만료", "서명 시각이 서버 시각과 너무 다릅니다. Date 헤더에 맞추세요."),
    "signature_replayed": ("재사용된 서명", "이 nonce는 이미 사용되었습니다. 요청마다 새 값을 쓰세요."),
    "forbidden": ("금지됨", "이 계정은 그 작업을 할 수 없습니다."),
    "account_frozen": ("계정 동결됨", "이 계정은 지금 아무것도 할 수 없습니다."),
    "not_found": ("찾을 수 없음", "이 서버에 그런 것이 없습니다."),
    "conflict": ("충돌", "이미 있거나, 그사이 바뀌었거나, 업로드 위치가 다릅니다."),
    "gone": ("더 이상 없음", "만료, 취소, 소진되었거나 알 수 없습니다."),
    "precondition_failed": ("전제 조건 불충족", "읽은 뒤 데이터가 바뀌었습니다. 다시 읽으세요."),
    "too_large": ("너무 큼", "이 서버의 한도를 넘습니다."),
    "unsupported_schema": ("지원하지 않는 스키마", "이 서버는 이 문서 스키마를 읽지 않습니다."),
    "digest_mismatch": ("해시 불일치", "본문의 SHA-256이 알린 값과 다릅니다."),
    "slow_down": ("천천히", "요청이 너무 많습니다. 안내된 시간 뒤에 다시 시도하세요."),
    "internal": ("내부 오류", "서버에 오류가 났습니다. 나중에 다시 시도하세요."),
    "unavailable": ("사용할 수 없음", "서버가 바쁘거나 점검 중입니다. 나중에 다시 시도하세요."),
}

ZH_HANS = {
    "bad_request": ("请求无效", "请求格式不正确；预期格式见其文档。"),
    "key_required": ("需要设备密钥", "此服务器将每个令牌绑定到设备密钥：请在配对时发送密钥。"),
    "unauthorized": ("未授权", "令牌缺失、未知、已吊销或已过期：请配对此设备。"),
    "signature_required": ("需要签名", "此令牌绑定到设备密钥：请为请求签名。"),
    "signature_invalid": ("签名无效", "签名无法验证，或格式不符。"),
    "signature_expired": ("签名已过期", "签名时间与服务器时间相差太远：请按其 Date 标头校准。"),
    "signature_replayed": ("签名重放", "此 nonce 已使用过：每个请求使用新的。"),
    "forbidden": ("禁止访问", "此账户无权这样做。"),
    "account_frozen": ("账户已冻结", "此账户暂时不能执行任何操作。"),
    "not_found": ("未找到", "此服务器上没有该内容。"),
    "conflict": ("冲突", "已存在、期间已更改，或上传进度不在此处。"),
    "gone": ("已不存在", "已过期、已吊销、已用尽或未知。"),
    "precondition_failed": ("前提条件不满足", "读取后数据已更改：请重新读取。"),
    "too_large": ("过大", "超出此服务器的限制。"),
    "unsupported_schema": ("不支持的架构", "此服务器无法读取此文档架构。"),
    "digest_mismatch": ("摘要不符", "正文的 SHA-256 与声明的不一致。"),
    "slow_down": ("请放慢", "请求过多：请在指定时间后重试。"),
    "internal": ("内部错误", "服务器出错；请稍后重试。"),
    "unavailable": ("不可用", "服务器繁忙或正在维护；请稍后重试。"),
}

ZH_HANT = {
    "bad_request": ("請求無效", "請求格式不正確；預期格式見其文件。"),
    "key_required": ("需要裝置金鑰", "此伺服器將每個權杖綁定到裝置金鑰：請在配對時傳送金鑰。"),
    "unauthorized": ("未授權", "權杖缺失、未知、已撤銷或已過期：請配對此裝置。"),
    "signature_required": ("需要簽章", "此權杖綁定到裝置金鑰：請為請求簽章。"),
    "signature_invalid": ("簽章無效", "簽章無法驗證，或格式不符。"),
    "signature_expired": ("簽章已過期", "簽章時間與伺服器時間相差太遠：請依其 Date 標頭校準。"),
    "signature_replayed": ("簽章重送", "此 nonce 已使用過：每個請求使用新的。"),
    "forbidden": ("禁止存取", "此帳戶無權這樣做。"),
    "account_frozen": ("帳戶已凍結", "此帳戶暫時不能執行任何操作。"),
    "not_found": ("找不到", "此伺服器上沒有該內容。"),
    "conflict": ("衝突", "已存在、期間已變更，或上傳進度不在此處。"),
    "gone": ("已不存在", "已過期、已撤銷、已用盡或未知。"),
    "precondition_failed": ("前提條件不符", "讀取後資料已變更：請重新讀取。"),
    "too_large": ("過大", "超出此伺服器的限制。"),
    "unsupported_schema": ("不支援的結構描述", "此伺服器無法讀取此文件的結構描述。"),
    "digest_mismatch": ("摘要不符", "本文的 SHA-256 與宣告的不一致。"),
    "slow_down": ("請放慢", "請求過多：請在指定時間後重試。"),
    "internal": ("內部錯誤", "伺服器出錯；請稍後重試。"),
    "unavailable": ("無法使用", "伺服器忙碌或正在維護；請稍後重試。"),
}

ERRORS = {"fr": FR, "fr-CA": FR, "de": DE, "es": ES, "es-419": ES_419, "it": IT, "nl": NL, "pt": PT,
          "pt-BR": PT_BR, "ru": RU, "ja": JA, "ko": KO, "zh-Hans": ZH_HANS, "zh-Hant": ZH_HANT}


def best(prefs):
    """The language of this server's texts for a client's languages (Accept-Language's tags, best first):
    one of LANGUAGES; English when it has none of them."""
    for tag in prefs:
        parts = tag.lower().split("-")
        primary, rest = parts[0], set(parts[1:])
        if primary == "en":
            return "en"
        if primary == "fr":
            return "fr-CA" if "ca" in rest else "fr"
        if primary == "es":
            return "es-419" if rest & AMERICAS else "es"
        if primary == "pt":
            return "pt-BR" if "br" in rest else "pt"
        if primary == "zh":
            return "zh-Hant" if rest & HANT else "zh-Hans"
        if primary in ("de", "it", "nl", "ru", "ja", "ko"):
            return primary
    return "en"


def error(code, language):
    """(title, detail) of an error `code` in `language`, or None for English (the server's own words)."""
    return ERRORS.get(language, {}).get(code)
