/** A popover side beside the highlighted controls (wide screens; phones use a bottom sheet). */
export type Side = "bottom" | "top" | "right" | "left";

/**
 * The page a step lives on. Steps of one page follow each other with «Далее»; the next page's steps come when the
 * client gets there by acting on the page (adding the company, choosing financing, starting a questionnaire).
 */
export type TourPage =
  "home" | "onboarding" | "company" | "products" | "questionnaire";

export type TourStep = {
  page: TourPage;
  /** The `data-tour` names of the highlighted elements (the first shown match of each); the spotlight covers all. */
  anchors: string[];
  title: string;
  text: string;
  /** What the client does to go on when the next step is on another page. */
  action?: string;
  /** Popover sides in order of preference, when the default (below, above, right, left) would hide the next control. */
  sides?: Side[];
};

/** The client walkthrough, from the first visit to the questionnaire. */
export const TOUR_STEPS: TourStep[] = [
  {
    page: "home",
    anchors: ["add-company"],
    title: "Начните с компании",
    text: "Добавьте ИП или ООО, для которого ищете финансирование. По сведениям компании подберём подходящие продукты, а затем перейдём к анкете.",
    action: "Нажмите «Добавить компанию» — продолжим на следующей странице.",
  },
  {
    page: "onboarding",
    anchors: ["choose-company"],
    title: "Выберите компанию",
    text: "Выберите компанию из списка — её ИНН подставится автоматически. Сведения о компании соберём из реестра и открытых источников.",
  },
  {
    page: "onboarding",
    anchors: ["gosuslugi"],
    title: "Подтвердите полномочия",
    text: "Госуслуги передадут ваши ФИО и должность и подтвердят, что вы представляете компанию. Без подтверждения компанию не добавить.",
  },
  {
    page: "onboarding",
    anchors: ["consents"],
    title: "Разрешите проверку",
    text: "Отметьте оба разрешения: по ним запросим сведения о компании и её оборотах. Кредитная история на этом шаге не запрашивается.",
    action: "Затем нажмите «Добавить и проверить».",
    // Below the consents are «Добавить и проверить» and the remaining list: keep them free.
    sides: ["right", "top", "left", "bottom"],
  },
  {
    page: "company",
    anchors: ["find-financing"],
    title: "Сведения о компании собраны",
    text: "Ниже — что удалось узнать из реестра и об оборотах бизнеса: на этих сведениях строится предварительная оценка.",
    action:
      "Нажмите «Подобрать финансирование», чтобы выбрать сумму и сравнить продукты.",
  },
  {
    page: "products",
    anchors: ["amount-field", "amount-slider"],
    title: "Укажите сумму",
    text: "Передвиньте ползунок или введите сумму цифрами — продукты ниже пересчитаются. Цель, срок и залог выберете позже, в анкете.",
    // Below the slider are the preset amounts: keep them free.
    sides: ["top", "bottom", "right", "left"],
  },
  {
    page: "products",
    anchors: ["product-head", "product-explanation"],
    title: "Сравните продукты",
    text: "На карточке — подходит ли продукт вашей компании, что это за продукт, его особенности и кому он подходит. Оценка предварительная и не означает одобрения.",
    sides: ["right", "bottom", "left", "top"],
  },
  {
    page: "products",
    anchors: ["start-application"],
    title: "Начните анкету",
    text: "Выберите подходящий продукт и начните анкету — сумма перенесётся в неё автоматически.",
    action: "Нажмите «Начать анкету» на карточке продукта.",
  },
  {
    page: "questionnaire",
    anchors: ["questionnaire"],
    title: "Заполните анкету",
    text: "Пройдите шаги анкеты по порядку: ответы сохраняются при переходе между ними, к черновику можно вернуться из раздела «Мои заявки». Кредитную историю запросим только после отправки и с вашего согласия.",
  },
];
