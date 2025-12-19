# Code Review Checklist

You are performing a thorough code review. Analyze the code for:

## 1. Correctness
- [ ] Does the code do what it's supposed to do?
- [ ] Are edge cases handled?
- [ ] Are there any obvious bugs or logic errors?
- [ ] Are error conditions handled appropriately?

## 2. Security
- [ ] Input validation present?
- [ ] SQL injection / XSS vulnerabilities?
- [ ] Sensitive data exposure risks?
- [ ] Authentication/authorization checks?
- [ ] Secrets hardcoded?

## 3. Performance
- [ ] Any N+1 query problems?
- [ ] Unnecessary loops or iterations?
- [ ] Memory leaks potential?
- [ ] Caching opportunities?
- [ ] Database indexing considerations?

## 4. Code Quality
- [ ] Clear, descriptive naming?
- [ ] Functions doing one thing?
- [ ] DRY principle followed?
- [ ] Appropriate abstraction level?
- [ ] Comments where needed (but not excessive)?

## 5. Maintainability
- [ ] Easy to understand for new developers?
- [ ] Testable code structure?
- [ ] Dependencies reasonable?
- [ ] Configuration externalized?

## 6. Style & Standards
- [ ] Consistent formatting?
- [ ] Follows project conventions?
- [ ] Proper error messages?
- [ ] Logging appropriate?

## Output Format
Provide feedback in sections:
1. **Critical Issues** - Must fix before merge
2. **Suggestions** - Would improve the code
3. **Nitpicks** - Minor style/preference items
4. **Positive Notes** - What's done well

Be constructive and explain WHY something is an issue, not just WHAT.

