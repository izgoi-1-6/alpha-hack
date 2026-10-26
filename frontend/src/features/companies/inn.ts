/**
 * The server's ИНН rule (`InnInput` in backend/app/schemas.py), checked in the browser before Госуслуги is asked: a
 * mistyped number gets a field message instead of a refusal the dialog could not explain. Ten digits for an ООО, twelve
 * for an ИП, not one digit repeated, and the standard check digits: each is the weighted digit sum mod 11 mod 10.
 */
const TENTH = [2, 4, 10, 3, 5, 9, 4, 6, 8];
const ELEVENTH = [7, 2, 4, 10, 3, 5, 9, 4, 6, 8];
const TWELFTH = [3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8];

const checkDigit = (digits: number[], weights: number[]) =>
  (weights.reduce((sum, weight, index) => sum + weight * digits[index], 0) %
    11) %
  10;

/** The field message for a complete ИНН that the server would refuse; null when it is valid or not complete yet. */
export function innProblem(inn: string): string | null {
  if (!/^(\d{10}|\d{12})$/.test(inn)) return null;
  const digits = [...inn].map(Number);
  if (new Set(digits).size === 1)
    return "Некорректный ИНН: все цифры одинаковые. Проверьте номер или выберите компанию из списка.";
  const valid =
    digits.length === 10
      ? checkDigit(digits, TENTH) === digits[9]
      : checkDigit(digits, ELEVENTH) === digits[10] &&
        checkDigit(digits, TWELFTH) === digits[11];
  return valid
    ? null
    : "Неверная контрольная сумма ИНН. Проверьте цифры или выберите компанию из списка.";
}
