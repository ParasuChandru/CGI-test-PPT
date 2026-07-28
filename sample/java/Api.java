public class Api {
    public String handleGetUser(int id) {
        Service service = new Service();
        return service.getUser(id);
    }
}
