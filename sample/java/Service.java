public class Service {
    public String getUser(int userId) {
        String raw = fetchRaw(userId);
        return Utils.formatName(raw);
    }

    private String fetchRaw(int userId) {
        return "user" + userId;
    }
}
