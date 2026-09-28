// Staff interface copy is translated in the browser. Customer names, products and
// campaign messages remain exactly as entered by people.
(() => {
  const copy = {
    "El Molino · Equipo": ["El Molino · Команда", "El Molino · Team"],
    "PANEL DEL EQUIPO": ["ПАНЕЛЬ СОТРУДНИКОВ", "STAFF PANEL"],
    "Salir": ["Выйти", "Sign out"],
    "Ir al Club": ["Открыть клуб", "Open Club"],
    "OPERACIÓN DIARIA": ["ЕЖЕДНЕВНАЯ РАБОТА", "DAILY OPERATIONS"],
    "Panel del equipo": ["Панель сотрудников", "Staff panel"],
    "Caja y gerencia, cada una con sus herramientas en un solo lugar.": ["Касса и управление — все инструменты в одном месте.", "Cashier and management tools in one place."],
    "ACCESO PERSONAL": ["ЛИЧНЫЙ ДОСТУП", "PERSONAL ACCESS"],
    "Entra con tu código": ["Вход по личному коду", "Sign in with your code"],
    "Usa el código que te entregó la gerencia. Cada acción quedará registrada en tu cuenta.": ["Введите код, выданный руководителем. Действия будут записаны в вашей учётной записи.", "Enter the code given to you by your manager. Your actions will be recorded under your account."],
    "Código personal": ["Личный код", "Personal code"],
    "Entrar": ["Войти", "Sign in"],
    "Crear la cuenta principal": ["Создать учётную запись владельца", "Create owner account"],
    "Tu nombre": ["Ваше имя", "Your name"],
    "Clave actual de gerencia": ["Действующий ключ управления", "Current management key"],
    "Crear cuenta": ["Создать учётную запись", "Create account"],
    "Recuperar código principal": ["Восстановить код владельца", "Recover owner code"],
    "Generar nuevo código": ["Создать новый код", "Generate new code"],
    "Caja": ["Касса", "Cashier"],
    "Gerencia": ["Управление", "Management"],
    "Vista previa. Para usar caja y gerencia, abre": ["Предпросмотр. Чтобы пользоваться кассой и управлением, запустите", "Preview. To use cashier and management, open"],
    "y entra en": ["и откройте", "and visit"],
    "Clientes y tickets": ["Клиенты и чеки", "Customers and receipts"],
    "Entregar recompensa": ["Выдать награду", "Give reward"],
    "01 · ATENCIÓN AL CLIENTE": ["01 · ОБСЛУЖИВАНИЕ КЛИЕНТА", "01 · CUSTOMER SERVICE"],
    "Teléfono del cliente": ["Телефон клиента", "Customer phone"],
    "Buscar cliente": ["Найти клиента", "Find customer"],
    "puntos ·": ["баллов ·", "points ·"],
    "Últimos tickets": ["Последние чеки", "Recent receipts"],
    "NUEVO CLIENTE": ["НОВЫЙ КЛИЕНТ", "NEW CUSTOMER"],
    "Registrar al Club": ["Зарегистрировать в клубе", "Register for the Club"],
    "Pide el nombre y confirma el teléfono con el cliente.": ["Уточните имя и номер телефона у клиента.", "Ask for the customer's name and confirm their phone number."],
    "Nombre": ["Имя", "Name"],
    "Teléfono": ["Телефон", "Phone"],
    "El cliente acepta recibir novedades y promociones.": ["Клиент согласен получать новости и предложения.", "The customer agrees to receive news and promotions."],
    "Registrar cliente": ["Зарегистрировать клиента", "Register customer"],
    "REGISTRO DE VENTA": ["РЕГИСТРАЦИЯ ПРОДАЖИ", "SALE ENTRY"],
    "Registrar compra": ["Зарегистрировать покупку", "Record purchase"],
    "Número de ticket": ["Номер чека", "Receipt number"],
    "Buscar en Wansoft": ["Найти в Wansoft", "Find in Wansoft"],
    "Ticket encontrado": ["Чек найден", "Receipt found"],
    "Asignar puntos de este ticket": ["Начислить баллы за этот чек", "Assign points for this receipt"],
    "+ Añadir producto": ["+ Добавить товар", "+ Add item"],
    "Total del ticket": ["Сумма чека", "Receipt total"],
    "Registrar ticket": ["Зарегистрировать чек", "Record receipt"],
    "Producto": ["Товар", "Item"],
    "Quitar": ["Удалить", "Remove"],
    "Nombre del producto": ["Название товара", "Item name"],
    "Cantidad": ["Количество", "Quantity"],
    "Precio unitario (MXN)": ["Цена за единицу (MXN)", "Unit price (MXN)"],
    "Revisa que el total coincida con el ticket antes de registrarlo.": ["Перед регистрацией сверьте сумму с чеком.", "Check that the total matches the receipt before recording it."],
    "BENEFICIOS DEL CLUB": ["ПРИВИЛЕГИИ КЛУБА", "CLUB BENEFITS"],
    "Código de canje del cliente": ["Код награды клиента", "Customer redemption code"],
    "Verificar código": ["Проверить код", "Verify code"],
    "Confirmar entrega": ["Подтвердить выдачу", "Confirm delivery"],
    "Clientes": ["Клиенты", "Customers"],
    "Tickets": ["Чеки", "Receipts"],
    "Recompensas": ["Награды", "Rewards"],
    "Campañas": ["Кампании", "Campaigns"],
    "Equipo": ["Команда", "Team"],
    "Inicio": ["Главная", "Overview"],
    "CENTRO DE CONTROL": ["ЦЕНТР УПРАВЛЕНИЯ", "CONTROL CENTER"],
    "Programa de puntos": ["Бонусная программа", "Loyalty program"],
    "Todo el recorrido del Club en un lugar: clientes, tickets, recompensas, campañas y equipo.": ["Вся работа клуба в одном месте: клиенты, чеки, награды, кампании и команда.", "The whole Club workflow in one place: customers, receipts, rewards, campaigns, and team."],
    "01 · CLIENTES": ["01 · КЛИЕНТЫ", "01 · CUSTOMERS"],
    "02 · TICKETS": ["02 · ЧЕКИ", "02 · RECEIPTS"],
    "03 · RECOMPENSAS": ["03 · НАГРАДЫ", "03 · REWARDS"],
    "04 · CAMPAÑAS": ["04 · КАМПАНИИ", "04 · CAMPAIGNS"],
    "05 · EQUIPO": ["05 · КОМАНДА", "05 · TEAM"],
    "Conoce a tu comunidad": ["Узнавайте клиентов", "Know your customers"],
    "Segmentos y recomendaciones →": ["Сегменты и рекомендации →", "Segments and recommendations →"],
    "Comprueba los puntos": ["Проверяйте баллы", "Review points"],
    "Ventas y diferencias Wansoft →": ["Продажи и расхождения Wansoft →", "Sales and Wansoft differences →"],
    "Gestiona el catálogo": ["Управляйте каталогом", "Manage rewards"],
    "Ver recompensas": ["Показать награды", "View rewards"],
    "Vuelve a conectar": ["Возвращайте клиентов", "Reconnect with customers"],
    "Borradores y envíos →": ["Черновики и рассылки →", "Drafts and sends →"],
    "Controla el acceso": ["Управляйте доступом", "Control access"],
    "Permisos y acciones →": ["Права и действия →", "Permissions and actions →"],
    "CONOCE A TUS CLIENTES": ["УЗНАЙТЕ СВОИХ КЛИЕНТОВ", "KNOW YOUR CUSTOMERS"],
    "Segmento": ["Сегмент", "Segment"],
    "Nuevos": ["Новые", "New"],
    "Activos": ["Активные", "Active"],
    "Frecuentes": ["Постоянные", "Frequent"],
    "En riesgo": ["В зоне риска", "At risk"],
    "Ver audiencia": ["Показать клиентов", "View audience"],
    "Ver recomendaciones": ["Показать рекомендации", "View recommendations"],
    "CONTROL DE PUNTOS": ["КОНТРОЛЬ БАЛЛОВ", "POINTS CONTROL"],
    "Revisión de tickets": ["Проверка чеков", "Receipt review"],
    "Compara los últimos 50 tickets acreditados con las ventas cargadas desde Wansoft. Solo muestra diferencias; no modifica puntos.": ["Сравнивает последние 50 начисленных чеков с продажами из Wansoft. Показывает расхождения и не меняет баллы.", "Compares the latest 50 credited receipts with Wansoft sales. Shows differences without changing points."],
    "Revisar tickets": ["Проверить чеки", "Review receipts"],
    "Mostrar": ["Показать", "Show"],
    "Todas las diferencias": ["Все расхождения", "All differences"],
    "Pendientes de importar": ["Ожидают загрузки", "Awaiting import"],
    "Pendiente de importar": ["Ожидает загрузки", "Awaiting import"],
    "Importe diferente": ["Сумма отличается", "Amount differs"],
    "Productos diferentes": ["Товары отличаются", "Items differ"],
    "Número no verificable": ["Номер не проверен", "Number cannot be verified"],
    "Descargar CSV": ["Скачать CSV", "Download CSV"],
    "RECOMPENSAS": ["НАГРАДЫ", "REWARDS"],
    "Catálogo de recompensas": ["Каталог наград", "Rewards catalog"],
    "Las recompensas activas aparecen en el Club del cliente. Las pausadas se conservan aquí y pueden reactivarse.": ["Активные награды видны клиентам в клубе. Приостановленные остаются здесь, их можно включить снова.", "Active rewards appear in the customer Club. Paused rewards stay here and can be reactivated."],
    "Recompensas creadas": ["Созданные награды", "Created rewards"],
    "Nueva recompensa": ["Новая награда", "New reward"],
    "Descripción para el cliente": ["Описание для клиента", "Description for customers"],
    "Costo en puntos": ["Стоимость в баллах", "Cost in points"],
    "Crear recompensa": ["Создать награду", "Create reward"],
    "Activa": ["Активна", "Active"],
    "Pausada": ["Приостановлена", "Paused"],
    "Costo": ["Стоимость", "Cost"],
    "Costo:": ["Стоимость:", "Cost:"],
    "Editar": ["Изменить", "Edit"],
    "Pausar": ["Приостановить", "Pause"],
    "Guardar cambios": ["Сохранить изменения", "Save changes"],
    "Aún no hay recompensas. Crea la primera a la derecha.": ["Наград пока нет. Создайте первую в форме справа.", "No rewards yet. Create the first one using the form on the right."],
    "Cargando recompensas…": ["Загрузка наград…", "Loading rewards…"],
    "Recompensa actualizada.": ["Награда обновлена.", "Reward updated."],
    "Recompensa pausada.": ["Награда приостановлена.", "Reward paused."],
    "Recompensa activada.": ["Награда активирована.", "Reward activated."],
    "COMUNICACIÓN": ["РАССЫЛКИ", "COMMUNICATION"],
    "Campaña por segmento": ["Кампания по сегменту", "Campaign by segment"],
    "Canal": ["Канал", "Channel"],
    "SMS y Club": ["SMS и клуб", "SMS and Club"],
    "Email (solo en Club)": ["Email (только в клубе)", "Email (Club only)"],
    "Mensaje": ["Сообщение", "Message"],
    "Crear borrador": ["Создать черновик", "Create draft"],
    "Activar una campaña la muestra en el Club. Si eliges SMS, el envío se inicia después, por separado, y puede generar cargos.": ["Активация показывает кампанию в клубе. Отправка SMS запускается отдельно и может быть платной.", "Activating a campaign shows it in the Club. SMS sending starts separately and may incur charges."],
    "Campañas creadas": ["Созданные кампании", "Created campaigns"],
    "Actualizar lista": ["Обновить список", "Refresh list"],
    "ACCESO Y CONTROL": ["ДОСТУП И КОНТРОЛЬ", "ACCESS AND CONTROL"],
    "Crea un código personal y elige las tareas permitidas. El código se muestra una sola vez.": ["Создайте личный код и выберите разрешённые действия. Код показывается один раз.", "Create a personal code and choose allowed tasks. The code is shown only once."],
    "Nombre del empleado": ["Имя сотрудника", "Employee name"],
    "Permisos": ["Права доступа", "Permissions"],
    "Caja y tickets": ["Касса и чеки", "Cashier and receipts"],
    "Analítica y revisión": ["Аналитика и проверка", "Analytics and review"],
    "Crear empleado": ["Добавить сотрудника", "Create employee"],
    "Empleados": ["Сотрудники", "Employees"],
    "Acciones recientes": ["Недавние действия", "Recent actions"],
    "Actualizar acciones": ["Обновить действия", "Refresh actions"],
    "Área de trabajo": ["Рабочая область", "Work area"],
    "Tareas de caja": ["Задачи кассы", "Cashier tasks"],
    "Herramientas de gerencia": ["Инструменты управления", "Management tools"],
    "Cambiar idioma": ["Сменить язык", "Change language"],
    "Estado": ["Статус", "Status"],
    "Cliente": ["Клиент", "Customer"],
    "Fecha": ["Дата", "Date"],
    "Acreditado MXN": ["Начислено MXN", "Credited MXN"],
    "Wansoft MXN": ["Wansoft MXN", "Wansoft MXN"],
    "Diferencias de productos": ["Расхождения по товарам", "Item differences"],
    "No fue posible completar la solicitud.": ["Не удалось выполнить запрос.", "Could not complete the request."],
    "Entrando…": ["Выполняется вход…", "Signing in…"],
    "Tu código principal. Guárdalo ahora; no se volverá a mostrar.": ["Ваш код владельца. Сохраните его сейчас: повторно он не появится.", "Your owner code. Save it now; it will not be shown again."],
    "Cuenta creada. Guarda el código y pulsa Entrar.": ["Учётная запись создана. Сохраните код и нажмите «Войти».", "Account created. Save the code and press Sign in."],
    "Nuevo código principal. El anterior ya no sirve; guarda este código ahora.": ["Новый код владельца. Старый больше не действует; сохраните новый код.", "New owner code. The old one no longer works; save this code now."],
    "Código nuevo listo. Guárdalo y pulsa Entrar.": ["Новый код готов. Сохраните его и нажмите «Войти».", "New code ready. Save it and press Sign in."],
    "Cargando tickets…": ["Загрузка чеков…", "Loading receipts…"],
    "Todavía no hay tickets registrados.": ["Чеков пока нет.", "No receipts recorded yet."],
    "Ticket sin número": ["Чек без номера", "Receipt without number"],
    "Buscando…": ["Поиск…", "Searching…"],
    "Cliente encontrado.": ["Клиент найден.", "Customer found."],
    "Cliente no encontrado. Puedes registrarlo abajo.": ["Клиент не найден. Его можно зарегистрировать ниже.", "Customer not found. You can register them below."],
    "Registrando…": ["Регистрация…", "Recording…"],
    "Cliente registrado. Ya puedes registrar su compra.": ["Клиент зарегистрирован. Теперь можно добавить покупку.", "Customer registered. You can now record their purchase."],
    "Introduce el número de ticket Wansoft.": ["Введите номер чека Wansoft.", "Enter the Wansoft receipt number."],
    "Buscando ticket…": ["Поиск чека…", "Searching for receipt…"],
    "Revisa el ticket y asígnalo al cliente.": ["Проверьте чек и привяжите его к клиенту.", "Review the receipt and assign it to the customer."],
    "Asignando puntos…": ["Начисление баллов…", "Assigning points…"],
    "Revisa los productos del ticket.": ["Проверьте товары в чеке.", "Review the items on the receipt."],
    "Ya entregado": ["Уже выдано", "Already delivered"],
    "Pendiente de entrega": ["Ожидает выдачи", "Awaiting delivery"],
    "Verificando…": ["Проверка…", "Verifying…"],
    "Canje encontrado.": ["Награда найдена.", "Redemption found."],
    "Confirmando…": ["Подтверждение…", "Confirming…"],
    "Entrega confirmada.": ["Выдача подтверждена.", "Delivery confirmed."],
    "No hay resultados.": ["Нет результатов.", "No results."],
    "Cargando…": ["Загрузка…", "Loading…"],
    "No hay tickets en este filtro.": ["По этому фильтру чеков нет.", "No receipts match this filter."],
    "Revisar": ["Проверить", "Review"],
    "sin venta Wansoft cargada": ["продажа Wansoft не загружена", "Wansoft sale not imported"],
    "Comparando tickets…": ["Сравнение чеков…", "Comparing receipts…"],
    "Todavía no hay tickets acreditados.": ["Начисленных чеков пока нет.", "No credited receipts yet."],
    "Guardando…": ["Сохранение…", "Saving…"],
    "No hay campañas.": ["Кампаний пока нет.", "No campaigns yet."],
    "Ver resultados": ["Показать результаты", "View results"],
    "Revisar y activar": ["Проверить и активировать", "Review and activate"],
    "La activación solo muestra la campaña en el Club. El envío de SMS requiere otra acción.": ["Активация только показывает кампанию в клубе. SMS отправляется отдельным действием.", "Activation only shows the campaign in the Club. Sending SMS requires a separate action."],
    "Activar en el Club": ["Активировать в клубе", "Activate in Club"],
    "Sin mensaje": ["Без сообщения", "No message"],
    "Revisar envío SMS": ["Проверить отправку SMS", "Review SMS sending"],
    "Ver estado de SMS": ["Показать статус SMS", "View SMS status"],
    "Mostrar más": ["Показать ещё", "Show more"],
    "Aceptado por LabsMobile": ["Принято LabsMobile", "Accepted by LabsMobile"],
    "Sin confirmación": ["Без подтверждения", "Unconfirmed"],
    "Teléfono inválido": ["Неверный телефон", "Invalid phone"],
    "Sin consentimiento vigente": ["Нет действующего согласия", "No valid consent"],
    "Visto en el Club": ["Просмотрено в клубе", "Seen in Club"],
    "Pendiente": ["Ожидает", "Pending"],
    "Cada envío puede generar cargos en LabsMobile. Los intentos sin confirmación no se reenvían automáticamente.": ["Каждая отправка может оплачиваться в LabsMobile. Попытки без подтверждения автоматически не повторяются.", "Each send may incur LabsMobile charges. Unconfirmed attempts are not retried automatically."],
    "Enviar hasta 5 SMS": ["Отправить до 5 SMS", "Send up to 5 SMS"],
    "El SMS supera 160 caracteres; crea otra campaña con un texto más corto.": ["SMS длиннее 160 символов. Создайте кампанию с более коротким текстом.", "The SMS exceeds 160 characters; create a campaign with shorter text."],
    "Analítica": ["Аналитика", "Analytics"],
    "Buscó cliente": ["Искал клиента", "Searched for customer"],
    "Consultó compras": ["Просмотрел покупки", "Viewed purchases"],
    "Buscó ticket Wansoft": ["Искал чек Wansoft", "Searched Wansoft receipt"],
    "Asignó ticket y puntos": ["Привязал чек и начислил баллы", "Assigned receipt and points"],
    "Registró cliente": ["Зарегистрировал клиента", "Registered customer"],
    "Registró compra": ["Зарегистрировал покупку", "Recorded purchase"],
    "Consultó canje": ["Проверил награду", "Viewed redemption"],
    "Entregó recompensa": ["Выдал награду", "Delivered reward"],
    "Consultó audiencia": ["Просмотрел сегмент клиентов", "Viewed audience"],
    "Revisó tickets": ["Проверил чеки", "Reviewed receipts"],
    "Creó recompensa": ["Создал награду", "Created reward"],
    "Actualizó recompensa": ["Изменил награду", "Updated reward"],
    "Creó campaña": ["Создал кампанию", "Created campaign"],
    "Activó campaña": ["Активировал кампанию", "Activated campaign"],
    "Envió campaña SMS": ["Отправил SMS-кампанию", "Sent SMS campaign"],
    "Creó cuenta de empleado": ["Создал учётную запись сотрудника", "Created employee account"],
    "Cambió acceso de empleado": ["Изменил доступ сотрудника", "Changed employee access"],
    "Cambió código de empleado": ["Сменил код сотрудника", "Changed employee code"],
    "Entró al panel": ["Вошёл в панель", "Signed in to the panel"],
    "Salió del panel": ["Вышел из панели", "Signed out of the panel"],
    "Todavía no hay acciones.": ["Действий пока нет.", "No actions yet."],
    "Guardar permisos": ["Сохранить права", "Save permissions"],
    "Desactivar": ["Отключить", "Deactivate"],
    "Activar": ["Включить", "Activate"],
    "Nuevo código": ["Новый код", "New code"],
    "Principal": ["Владелец", "Owner"],
    "Desactivado": ["Отключён", "Deactivated"],
    "Clave de gerencia incorrecta": ["Неверный ключ управления", "Incorrect management key"],
    "La cuenta principal ya existe": ["Учётная запись владельца уже существует", "Owner account already exists"],
    "Código incorrecto o cuenta desactivada": ["Неверный код или учётная запись отключена", "Incorrect code or deactivated account"],
    "Acceso denegado": ["Доступ запрещён", "Access denied"],
    "Sesión inválida o vencida": ["Сессия недействительна или истекла", "Invalid or expired session"],
    "Se requiere una sesión válida": ["Нужна действующая сессия", "A valid session is required"],
    "No autorizado para este cliente": ["Нет доступа к этому клиенту", "Not authorized for this customer"],
    "Tu cuenta no tiene permiso para esta acción": ["У вашей учётной записи нет права на это действие", "Your account does not have permission for this action"],
    "Sesión vencida. Vuelve a entrar": ["Сессия истекла. Войдите снова", "Session expired. Please sign in again"],
    "Entra con tu código personal": ["Войдите по личному коду", "Sign in with your personal code"],
    "Solo la cuenta principal administra el equipo": ["Управлять командой может только владелец", "Only the owner account can manage the team"],
    "La cuenta principal no existe": ["Учётная запись владельца не найдена", "Owner account does not exist"],
    "Empleado no encontrado": ["Сотрудник не найден", "Employee not found"],
    "Cliente no encontrado": ["Клиент не найден", "Customer not found"],
    "Número de ticket inválido": ["Неверный номер чека", "Invalid receipt number"],
    "Ticket no encontrado en los reportes Wansoft": ["Чек не найден в отчётах Wansoft", "Receipt not found in Wansoft reports"],
    "El envío de SMS no está configurado": ["Отправка SMS не настроена", "SMS sending is not configured"],
    "Código inválido o vencido": ["Код неверен или истёк", "Invalid or expired code"],
    "Database unavailable": ["База данных недоступна", "Database unavailable"],
  };

  // Patterns cover values assembled at runtime. Text supplied by customers or
  // employees is captured and kept verbatim in each translated message.
  const patterns = [
    [/^(.+) · (.+) · \+(\d+) puntos$/, (m) => [`${m[1]} · ${m[2]} · +${m[3]} баллов`, `${m[1]} · ${m[2]} · +${m[3]} points`]],
    [/^(.+) · (.+) · (.+) · (\d+) productos$/, (m) => [`${m[1]} · ${m[2]} · ${m[3]} · ${m[4]} товаров`, `${m[1]} · ${m[2]} · ${m[3]} · ${m[4]} items`]],
    [/^(.+) · Principal · Desactivado$/, (m) => [`${m[1]} · Владелец · Отключён`, `${m[1]} · Owner · Deactivated`]],
    [/^(.+) · Principal$/, (m) => [`${m[1]} · Владелец`, `${m[1]} · Owner`]],
    [/^(.+) · Desactivado$/, (m) => [`${m[1]} · Отключён`, `${m[1]} · Deactivated`]],
    [/^(\d+) puntos$/, (m) => [`${m[1]} баллов`, `${m[1]} points`]],
    [/^\+(\d+) puntos$/, (m) => [`+${m[1]} баллов`, `+${m[1]} points`]],
    [/^(\d+) productos$/, (m) => [`${m[1]} товаров`, `${m[1]} items`]],
    [/^Producto (\d+)$/, (m) => [`Товар ${m[1]}`, `Item ${m[1]}`]],
    [/^Ticket (\S+)$/, (m) => [`Чек ${m[1]}`, `Receipt ${m[1]}`]],
    [/^Ticket Wansoft (.+): (\d+) puntos asociados\.$/, (m) => [`Чек Wansoft ${m[1]}: начислено ${m[2]} баллов.`, `Wansoft receipt ${m[1]}: ${m[2]} points assigned.`]],
    [/^Ticket procesado\. (\d+) puntos asociados\. ID: (.+)$/, (m) => [`Чек обработан. Начислено ${m[1]} баллов. ID: ${m[2]}`, `Receipt processed. ${m[1]} points assigned. ID: ${m[2]}`]],
    [/^(\d+) compras · (\d+) puntos · (.+) MXN$/, (m) => [`${m[1]} покупок · ${m[2]} баллов · ${m[3]} MXN`, `${m[1]} purchases · ${m[2]} points · ${m[3]} MXN`]],
    [/^(\d+) clientes en el segmento\.$/, (m) => [`Клиентов в сегменте: ${m[1]}.`, `${m[1]} customers in segment.`]],
    [/^(\d+) recomendaciones\.$/, (m) => [`Рекомендаций: ${m[1]}.`, `${m[1]} recommendations.`]],
    [/^(\d+) de (\d+) tickets coinciden\. (\d+) requieren revisión\. Mostrando (\d+)\.$/, (m) => [`Совпадают ${m[1]} из ${m[2]} чеков. Требуют проверки: ${m[3]}. Показано: ${m[4]}.`, `${m[1]} of ${m[2]} receipts match. ${m[3]} need review. Showing ${m[4]}.`]],
    [/^(.+) · acreditado (.+) · (.+)$/, (m) => [`${m[1]} · начислено ${m[2]} · ${translate(m[3])}`, `${m[1]} · credited ${m[2]} · ${translate(m[3])}`]],
    [/^(.+) · \$(.+): acreditado (.+) \/ Wansoft (.+); importe \$(.+) \/ \$(.+)$/, (m) => [`${m[1]} · $${m[2]}: начислено ${m[3]} / Wansoft ${m[4]}; сумма $${m[5]} / $${m[6]}`, `${m[1]} · $${m[2]}: credited ${m[3]} / Wansoft ${m[4]}; amount $${m[5]} / $${m[6]}`]],
    [/^Recompensa creada: (.+)\. Ya está visible en el Club\.$/, (m) => [`Награда «${m[1]}» создана и видна в клубе.`, `Reward “${m[1]}” was created and is visible in the Club.`]],
    [/^(\d+) activas · (\d+) en total$/, (m) => [`Активных: ${m[1]} · всего: ${m[2]}`, `${m[1]} active · ${m[2]} total`]],
    [/^(\d+) recompensas en el catálogo\.$/, (m) => [`Наград в каталоге: ${m[1]}.`, `${m[1]} rewards in the catalog.`]],
    [/^(\d+) puntos$/, (m) => [`${m[1]} баллов`, `${m[1]} points`]],
    [/^Borrador creado para (\d+) clientes\. ID: (.+)$/, (m) => [`Черновик для ${m[1]} клиентов создан. ID: ${m[2]}`, `Draft created for ${m[1]} customers. ID: ${m[2]}`]],
    [/^(\d+) campañas\.$/, (m) => [`Кампаний: ${m[1]}.`, `${m[1]} campaigns.`]],
    [/^(.+) · (.+) · (\d+) destinatarios$/, (m) => [`${m[1]} · ${m[2]} · получателей: ${m[3]}`, `${m[1]} · ${m[2]} · ${m[3]} recipients`]],
    [/^(\d+) aperturas · (\d+) clics$/, (m) => [`${m[1]} открытий · ${m[2]} нажатий`, `${m[1]} opens · ${m[2]} clicks`]],
    [/^(\d+) destinatarios con consentimiento · (\d+) excluidos$/, (m) => [`${m[1]} получателей с согласием · исключено ${m[2]}`, `${m[1]} recipients with consent · ${m[2]} excluded`]],
    [/^Mostrando (\d+) de (\d+) destinatarios\.$/, (m) => [`Показано ${m[1]} из ${m[2]} получателей.`, `Showing ${m[1]} of ${m[2]} recipients.`]],
    [/^(\d+) pendientes · (\d+) aceptados · (\d+) sin confirmación · (\d+) teléfonos inválidos · (\d+) sin consentimiento vigente$/, (m) => [`Ожидают ${m[1]} · принято ${m[2]} · без подтверждения ${m[3]} · неверных номеров ${m[4]} · без согласия ${m[5]}`, `${m[1]} pending · ${m[2]} accepted · ${m[3]} unconfirmed · ${m[4]} invalid phones · ${m[5]} without consent`]],
    [/^(\d+) aceptados · (\d+) sin confirmación · (\d+) teléfonos inválidos · (\d+) pendientes\.$/, (m) => [`Принято ${m[1]} · без подтверждения ${m[2]} · неверных номеров ${m[3]} · ожидают ${m[4]}.`, `${m[1]} accepted · ${m[2]} unconfirmed · ${m[3]} invalid phones · ${m[4]} pending.`]],
    [/^Código personal de (.+)\. Cópialo ahora; solo se muestra una vez\.$/, (m) => [`Личный код для ${m[1]}. Скопируйте его сейчас: он показывается один раз.`, `Personal code for ${m[1]}. Copy it now; it is shown only once.`]],
    [/^Permisos guardados para (.+)\.$/, (m) => [`Права для ${m[1]} сохранены.`, `Permissions saved for ${m[1]}.`]],
    [/^Cuenta creada para (.+)\.$/, (m) => [`Учётная запись для ${m[1]} создана.`, `Account created for ${m[1]}.`]],
    [/^¿Entregar (.+) a (.+)\?$/, (m) => [`Выдать награду «${m[1]}» клиенту ${m[2]}?`, `Give ${m[1]} to ${m[2]}?`]],
    [/^¿Mostrar (.+) a (\d+) clientes en el Club\?$/, (m) => [`Показать кампанию «${m[1]}» ${m[2]} клиентам клуба?`, `Show ${m[1]} to ${m[2]} Club customers?`]],
    [/^¿Enviar hasta (\d+) SMS de (.+)\? Puede generar cargos\.$/, (m) => [`Отправить до ${m[1]} SMS для кампании «${m[2]}»? Возможна оплата.`, `Send up to ${m[1]} SMS for ${m[2]}? Charges may apply.`]],
  ];

  let language;
  try { language = localStorage.getItem("el-molino-staff-language") || "es"; } catch (_) { language = "es"; }
  if (!["es", "ru", "en"].includes(language)) language = "es";
  const localeCodes = { es: "es-MX", ru: "ru-RU", en: "en-US" };
  const names = { es: "Español", ru: "Русский", en: "English" };
  const originals = new WeakMap();
  const listeners = [];

  function translate(value) {
    if (language === "es" || !value) return value;
    const exact = copy[value];
    if (exact) return exact[language === "ru" ? 0 : 1];
    for (const [pattern, result] of patterns) {
      const match = value.match(pattern);
      if (match) return result(match)[language === "ru" ? 0 : 1];
    }
    return value;
  }

  const campaignStates = {
    draft: ["Borrador", "Черновик", "Draft"], active: ["Activa", "Активна", "Active"], paused: ["Pausada", "Приостановлена", "Paused"],
  };
  const campaignChannels = { sms: ["SMS y Club", "SMS и клуб", "SMS and Club"], push: ["Club", "Клуб", "Club"], email: ["Email", "Email", "Email"] };
  function localizedValue(value, labels) {
    return labels[value]?.[{ es: 0, ru: 1, en: 2 }[language]] || value;
  }

  function localizeNode(node) {
    if (!node.nodeValue?.trim() || node.parentElement?.closest("script,style")) return;
    let record = originals.get(node);
    if (!record || node.nodeValue !== record.last) record = { source: node.nodeValue, last: node.nodeValue };
    const match = record.source.match(/^(\s*)([\s\S]*?)(\s*)$/);
    const translated = match[1] + translate(match[2]) + match[3];
    record.last = translated;
    originals.set(node, record);
    if (node.nodeValue !== translated) node.nodeValue = translated;
  }

  function localizeTree(root) {
    if (root.nodeType === Node.TEXT_NODE) { localizeNode(root); return; }
    if (root.nodeType !== Node.ELEMENT_NODE && root.nodeType !== Node.DOCUMENT_FRAGMENT_NODE) return;
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    while (walker.nextNode()) localizeNode(walker.currentNode);
  }

  const observer = new MutationObserver((changes) => {
    for (const change of changes) {
      if (change.type === "characterData") localizeNode(change.target);
      else change.addedNodes.forEach(localizeTree);
    }
  });

  function applyLanguage() {
    document.documentElement.lang = localeCodes[language];
    document.title = translate("El Molino · Equipo");
    document.getElementById("staff-language-current").textContent = names[language];
    document.querySelectorAll("[aria-label]").forEach((element) => {
      if (!element.dataset.originalAriaLabel) element.dataset.originalAriaLabel = element.getAttribute("aria-label");
      element.setAttribute("aria-label", translate(element.dataset.originalAriaLabel));
    });
    localizeTree(document.body);
    listeners.forEach((listener) => listener());
  }

  function setLanguage(next) {
    if (!["es", "ru", "en"].includes(next)) return;
    language = next;
    try { localStorage.setItem("el-molino-staff-language", next); } catch (_) { /* Private browsing. */ }
    applyLanguage();
  }

  const toggle = document.getElementById("staff-language-button");
  const menu = document.getElementById("staff-language-menu");
  function closeMenu() { menu.hidden = true; toggle.setAttribute("aria-expanded", "false"); }
  toggle.addEventListener("click", () => {
    menu.hidden = !menu.hidden;
    toggle.setAttribute("aria-expanded", String(!menu.hidden));
  });
  menu.querySelectorAll("[data-language]").forEach((button) => button.addEventListener("click", () => {
    setLanguage(button.dataset.language);
    closeMenu();
    toggle.focus();
  }));
  document.addEventListener("click", (event) => { if (!event.target.closest(".staff-language")) closeMenu(); });
  document.addEventListener("keydown", (event) => { if (event.key === "Escape") closeMenu(); });
  observer.observe(document.body, { subtree: true, childList: true, characterData: true });
  applyLanguage();
  window.staffI18n = {
    translate, locale: () => localeCodes[language],
    campaignState: (value) => localizedValue(value, campaignStates),
    campaignChannel: (value) => localizedValue(value, campaignChannels),
    onChange: (listener) => listeners.push(listener),
  };
})();
